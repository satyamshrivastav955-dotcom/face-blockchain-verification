"""C2PA write path: embed a FaceProof reference, read it back, tamper, and check trust handling.

The signing certificate is generated here (a throwaway test CA). It validates but is, correctly,
reported as an UNTRUSTED signer unless the test CA is passed as a trust anchor.
"""

from __future__ import annotations

import datetime

import cv2
import numpy as np
import pytest

pytest.importorskip("c2pa")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: E402

from src.evidence.record import seal  # noqa: E402
from src.verification.c2pa_check import inspect_content_credentials  # noqa: E402
from src.verification.c2pa_write import C2paWriteError, embed_record_reference  # noqa: E402


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, cn), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FaceProof Test")]
    )


@pytest.fixture(scope="module")
def pki():
    now = datetime.datetime.now(datetime.timezone.utc)
    root_key = ec.generate_private_key(ec.SECP256R1())
    root = (
        x509.CertificateBuilder()
        .subject_name(_name("FaceProof Test Root"))
        .issuer_name(_name("FaceProof Test Root"))
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name("FaceProof Test Signer"))
        .issuer_name(_name("FaceProof Test Root"))
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    return {
        "chain": (leaf.public_bytes(pem) + root.public_bytes(pem)).decode(),
        "key": leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
        "root": root.public_bytes(pem).decode(),
    }


@pytest.fixture
def jpeg():
    rng = np.random.default_rng(3)
    img = (rng.random((96, 96, 3)) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def record():
    return seal({"schema": "faceproof/attestation/v1", "source_image": {"sha256": "ab" * 32}})


def _embed(jpeg, record, pki):
    return embed_record_reference(jpeg, record, cert_chain_pem=pki["chain"], private_key_pem=pki["key"])


def test_roundtrip_exposes_the_record_hash(jpeg, record, pki):
    signed = _embed(jpeg, record, pki)
    cc = inspect_content_credentials(signed)
    assert cc.state == "valid"
    assert cc.faceproof_record_hash == record["integrity"]["verification_hash"]


def test_self_made_certificate_is_untrusted_by_default(jpeg, record, pki):
    cc = inspect_content_credentials(_embed(jpeg, record, pki))
    assert cc.untrusted_signer is True and cc.trusted is False


def test_trust_anchor_makes_the_signer_trusted(jpeg, record, pki):
    cc = inspect_content_credentials(_embed(jpeg, record, pki), trust_anchors_pem=pki["root"])
    assert cc.state == "valid" and cc.trusted is True and cc.untrusted_signer is False


def test_a_different_trust_anchor_does_not_trust_it(jpeg, record, pki):
    other = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    stranger = (
        x509.CertificateBuilder()
        .subject_name(_name("Stranger"))
        .issuer_name(_name("Stranger"))
        .public_key(other.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=5))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(other, hashes.SHA256())
    )
    pem = stranger.public_bytes(serialization.Encoding.PEM).decode()
    cc = inspect_content_credentials(_embed(jpeg, record, pki), trust_anchors_pem=pem)
    assert cc.trusted is False


def test_pixel_edit_after_signing_invalidates_the_manifest(jpeg, record, pki):
    signed = bytearray(_embed(jpeg, record, pki))
    # flip a byte deep in the entropy-coded image data (past the embedded manifest at the front)
    signed[-200] ^= 0xFF
    cc = inspect_content_credentials(bytes(signed))
    assert cc.state == "invalid"


def test_stripping_the_manifest_is_silent_absence_not_a_pass(jpeg, record, pki):
    # Re-encoding drops the manifest: C2PA reports "absent", which proves nothing.
    arr = cv2.imdecode(np.frombuffer(_embed(jpeg, record, pki), np.uint8), cv2.IMREAD_COLOR)
    ok, buf = cv2.imencode(".jpg", arr)
    assert ok
    cc = inspect_content_credentials(buf.tobytes())
    assert cc.state == "absent" and cc.faceproof_record_hash == ""


def test_bad_certificate_is_a_clear_error(jpeg, record, pki):
    with pytest.raises(C2paWriteError):
        embed_record_reference(jpeg, record, cert_chain_pem="nope", private_key_pem=pki["key"])


def test_unsupported_format_and_missing_hash(record, pki):
    with pytest.raises(C2paWriteError):
        embed_record_reference(b"not an image", record, cert_chain_pem=pki["chain"], private_key_pem=pki["key"])
    with pytest.raises(C2paWriteError):
        embed_record_reference(
            b"\xff\xd8\xff" + b"\0" * 20, {"integrity": {}}, cert_chain_pem=pki["chain"], private_key_pem=pki["key"]
        )


def test_cli_embed_then_check_against_the_record(tmp_path, jpeg, record, pki, capsys):
    from src.evidence.record import save_record
    from src.main import main

    img = tmp_path / "p.jpg"
    img.write_bytes(jpeg)
    rec = save_record(record, tmp_path / "r.json")
    (tmp_path / "chain.pem").write_text(pki["chain"])
    (tmp_path / "key.pem").write_text(pki["key"])
    env = tmp_path / "e.env"
    env.write_text("")
    common = ["--ascii", "--env", str(env)]
    assert (
        main(
            [
                "c2pa-embed",
                "--image",
                str(img),
                "--record",
                str(rec),
                "--cert-chain",
                str(tmp_path / "chain.pem"),
                "--key",
                str(tmp_path / "key.pem"),
                *common,
            ]
        )
        == 0
    )
    out = tmp_path / "p.c2pa.jpg"
    assert out.exists() and out.read_bytes() != jpeg
    assert main(["c2pa-check", "--image", str(out), "--record", str(rec), *common]) == 0
    # a different record is not referenced by this file
    other = save_record(seal({"schema": "faceproof/attestation/v1", "x": 1}), tmp_path / "o.json")
    assert main(["c2pa-check", "--image", str(out), "--record", str(other), *common]) == 2
    # the source image is never overwritten
    assert (
        main(
            [
                "c2pa-embed",
                "--image",
                str(img),
                "--record",
                str(rec),
                "--cert-chain",
                str(tmp_path / "chain.pem"),
                "--key",
                str(tmp_path / "key.pem"),
                "--output",
                str(img),
                *common,
            ]
        )
        == 1
    )
