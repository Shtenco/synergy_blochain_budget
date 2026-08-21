// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SynergyBudgetAnchorRegistry
/// @notice Immutable audit anchors for public budget snapshots.
contract SynergyBudgetAnchorRegistry {
    address public owner;
    mapping(address => bool) public publisher;

    struct Anchor {
        bytes32 recordMerkleRoot;
        bytes32 artifactMerkleRoot;
        bytes32 manifestHash;
        bytes32 snapshotId;
        uint64 asOf;
        uint64 anchoredAt;
        address publisherAddress;
        string uri;
    }

    mapping(bytes32 => mapping(uint256 => Anchor)) private anchors;
    mapping(bytes32 => uint256) public latestVersion;

    event PublisherChanged(address indexed account, bool allowed);
    event BudgetSnapshotAnchored(bytes32 indexed datasetId, uint256 indexed version, bytes32 indexed snapshotId, bytes32 recordMerkleRoot, bytes32 artifactMerkleRoot, bytes32 manifestHash, uint64 asOf, string uri);

    error NotOwner();
    error NotPublisher();
    error InvalidRoot();
    error InvalidAsOf();

    constructor() {
        owner = msg.sender;
        publisher[msg.sender] = true;
        emit PublisherChanged(msg.sender, true);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyPublisher() {
        if (!publisher[msg.sender]) revert NotPublisher();
        _;
    }

    function setPublisher(address account, bool allowed) external onlyOwner {
        publisher[account] = allowed;
        emit PublisherChanged(account, allowed);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero owner");
        owner = newOwner;
    }

    function anchor(bytes32 datasetId, bytes32 snapshotId, bytes32 recordMerkleRoot, bytes32 artifactMerkleRoot, bytes32 manifestHash, uint64 asOf, string calldata uri) external onlyPublisher returns (uint256 version) {
        if (recordMerkleRoot == bytes32(0) && artifactMerkleRoot == bytes32(0)) revert InvalidRoot();
        if (asOf == 0 || asOf > block.timestamp + 1 days) revert InvalidAsOf();
        version = latestVersion[datasetId] + 1;
        latestVersion[datasetId] = version;
        anchors[datasetId][version] = Anchor(recordMerkleRoot, artifactMerkleRoot, manifestHash, snapshotId, asOf, uint64(block.timestamp), msg.sender, uri);
        emit BudgetSnapshotAnchored(datasetId, version, snapshotId, recordMerkleRoot, artifactMerkleRoot, manifestHash, asOf, uri);
    }

    function getAnchor(bytes32 datasetId, uint256 version) external view returns (Anchor memory) {
        return anchors[datasetId][version];
    }
}
