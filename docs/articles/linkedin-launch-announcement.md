# LinkedIn Launch Announcement Draft

**Format:** Professional update for LinkedIn / Engineering Community  
**Author Voice:** Engineering Author / Maintainer  
**Status:** Ready for publication upon approval  

---

Reverse-image search is one of the most common ways to investigate where an image appeared online. But in practice, a search hit is only an ephemeral lead—pages get taken down, search indices change, and screenshots can be edited in seconds.

To solve this, I've released **FaceProof**—an open-source, evidence-first image provenance system that connects local computer vision, cryptographic integrity, and blockchain anchoring.

Instead of treating search results as truth, FaceProof introduces a structured, verifiable pipeline:

1. **Local-First Computer Vision**: Detects, aligns, and embeds faces directly on your workstation using OpenCV (YuNet + SFace) or ONNX Runtime (SCRFD + ArcFace). Feature vectors stay exclusively in local memory—no biometric data is ever stored on disk or sent over the network.
2. **Three-Tier Evidence Ladder**: Re-examines candidate images locally and enforces strict semantic honesty. It explicitly distinguishes biometric *face matches* from visual *image derivatives* (recovered via SIFT + RANSAC geometric homography or perceptual hashing). Image similarity is never inflated into an identity claim.
3. **SSRF-Guarded Network Pipeline**: Downloads candidate pages through IP-pinned sockets with redirect re-validation to defeat DNS rebinding and internal network exposure.
4. **Deterministic Cryptographic Sealing**: Canonicalizes the evidence payload using a restricted profile of RFC 8785 (JCS) and SHA-256 into an envelope schema (`faceverify/v2`).
5. **EVM Anchoring & Merkle Batches**: Records cryptographic commitments onto Base Sepolia using an immutable, first-write-wins Solidity registry. URLs are committed via Keccak-256 rather than plaintext, and an RFC 6962 Merkle-batch mechanism amortizes gas costs down to ~74 gas per record.

Crucially, FaceProof is an **image provenance tool, not an identity recognition system**. A blockchain commitment establishes *when* a specific record was anchored; it does not identify a human being or prove that a website is authentic.

The codebase includes 658 hermetic tests, full 10-fold cross-validated LFW benchmarks, and a local-first FastAPI + React interface.

* **GitHub Repository**: https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification
* **Interactive Showcase**: https://satyamshrivastav955-dotcom.github.io/face-blockchain-verification/
* **Technical Article**: [Link to Dev.to / Medium / GitHub article]

Feedback from computer vision engineers, cryptographers, and security researchers is warmly welcome!

#OpenSource #ComputerVision #Blockchain #Cryptography #Python #Web3 #SoftwareEngineering #DataPrivacy #CyberSecurity
