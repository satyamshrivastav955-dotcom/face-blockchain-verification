// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title  VerificationRegistry
/// @notice Append-only registry of face/image provenance verification hashes.
///
/// @dev DESIGN NOTES
///
/// 1. FIRST WRITE WINS. `register` reverts if a hash is already present. A
///    naive implementation writes `_records[dataHash] = Record(...)`
///    unconditionally, which lets anyone overwrite any existing record and
///    destroys the tamper-evidence the whole system claims to provide. The
///    guard below is the single most important line in this contract.
///
/// 2. NO ADMIN, NO OWNER, NO UPGRADE PATH, NO DELETE. There is deliberately no
///    privileged function anywhere. Append-only is a property of the bytecode
///    rather than a promise about who holds a key, so no one - including the
///    deployer - can alter or remove a record after the fact.
///
/// 3. THE SUBMITTER IS RECORDED. `msg.sender` is stored so a record is
///    attributable. It proves who asserted the claim; it does not make the
///    claim true. See the Limitations section of the README.
///
/// 4. THE URL IS HASHED IN STORAGE, FULL IN THE EVENT. Storing a string costs a
///    fresh 32-byte slot per 32 characters; a `keccak256` digest is one slot
///    regardless of length and still lets anyone prove which URL was
///    registered. The human-readable URL is emitted in the event, where data is
///    dramatically cheaper because it is never part of contract state.
///
/// 5. NO BIOMETRIC DATA IS STORED. Only a SHA-256 digest of the canonical
///    verification payload is ever written on-chain. No face embedding, no
///    image, no personal data. The chain therefore cannot leak a biometric
///    template even though the record is public and permanent.
contract VerificationRegistry {
    /// @dev Packed into exactly two storage slots.
    ///
    /// Slot 1: submitter (20 bytes) + timestamp (6) + blockNumber (6) = 32.
    /// Slot 2: urlHash (32).
    ///
    /// uint48 is not a premature micro-optimisation here: it makes the first
    /// three fields share one slot, saving a full SSTORE (~20k gas) per
    /// registration. uint48 seconds overflows in the year 8,921,556 and uint48
    /// blocks at 2.8e14, so neither bound is a practical concern.
    struct Record {
        address submitter;
        uint48 timestamp;
        uint48 blockNumber;
        bytes32 urlHash;
    }

    /// @dev Private so that all reads go through `verify`, which returns an
    ///      explicit `exists` flag. A public mapping getter returns a
    ///      zero-filled struct for an unknown key, which callers routinely
    ///      misread as a valid record.
    mapping(bytes32 => Record) private _records;

    /// @notice Total number of records ever registered.
    uint256 public totalRecords;

    /// @notice Emitted once per successful registration.
    /// @dev `dataHash`, `submitter` and `urlHash` are indexed so the explorer
    ///      and any log query can filter on them directly.
    event Registered(
        bytes32 indexed dataHash,
        address indexed submitter,
        bytes32 indexed urlHash,
        string sourceUrl,
        uint48 timestamp
    );

    /// @notice A record already exists for this hash and cannot be replaced.
    error AlreadyRegistered(bytes32 dataHash, uint48 registeredAt, address submitter);

    /// @notice The zero hash is not a meaningful commitment.
    error ZeroHash();

    /// @notice Register the verification hash of a provenance claim.
    /// @param dataHash  SHA-256 of the canonical verification payload.
    /// @param sourceUrl The matched social-media post URL, for the event log.
    /// @return timestamp The block timestamp the record was anchored at.
    function register(bytes32 dataHash, string calldata sourceUrl)
        external
        returns (uint48 timestamp)
    {
        if (dataHash == bytes32(0)) revert ZeroHash();

        Record storage existing = _records[dataHash];
        // `timestamp` doubles as the existence flag: block.timestamp is never
        // zero on any live chain, so a zero here can only mean "never written".
        if (existing.timestamp != 0) {
            revert AlreadyRegistered(dataHash, existing.timestamp, existing.submitter);
        }

        timestamp = uint48(block.timestamp);
        bytes32 urlHash = keccak256(bytes(sourceUrl));

        _records[dataHash] = Record({
            submitter: msg.sender,
            timestamp: timestamp,
            blockNumber: uint48(block.number),
            urlHash: urlHash
        });

        unchecked {
            // Cannot realistically overflow: one increment per transaction.
            totalRecords += 1;
        }

        emit Registered(dataHash, msg.sender, urlHash, sourceUrl, timestamp);
    }

    /// @notice Look up a record.
    /// @return exists      Whether anything is registered for `dataHash`.
    /// @return submitter   Address that registered it.
    /// @return timestamp   Block timestamp at registration.
    /// @return blockNumber Block height at registration.
    /// @return urlHash     keccak256 of the registered source URL.
    function verify(bytes32 dataHash)
        external
        view
        returns (
            bool exists,
            address submitter,
            uint48 timestamp,
            uint48 blockNumber,
            bytes32 urlHash
        )
    {
        Record storage r = _records[dataHash];
        return (r.timestamp != 0, r.submitter, r.timestamp, r.blockNumber, r.urlHash);
    }

    /// @notice Whether a hash has been registered.
    function isRegistered(bytes32 dataHash) external view returns (bool) {
        return _records[dataHash].timestamp != 0;
    }

    /// @notice Check a hash and a plaintext URL against the stored record in
    ///         one call, without trusting the caller's copy of either.
    function matchesUrl(bytes32 dataHash, string calldata sourceUrl)
        external
        view
        returns (bool)
    {
        Record storage r = _records[dataHash];
        return r.timestamp != 0 && r.urlHash == keccak256(bytes(sourceUrl));
    }
}
