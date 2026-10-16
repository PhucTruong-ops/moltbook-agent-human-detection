
CREATE DATABASE IF NOT EXISTS moltbook_research
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE moltbook_research;

CREATE TABLE IF NOT EXISTS accounts (
    account_id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255),
    description TEXT,
    created_at DATETIME NULL,
    last_active DATETIME NULL,
    karma BIGINT NULL,
    follower_count BIGINT NULL,
    following_count BIGINT NULL,
    is_claimed BOOLEAN NULL,
    is_active BOOLEAN NULL,
    raw_json JSON NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    post_id VARCHAR(100) PRIMARY KEY,
    author_id VARCHAR(100),
    title VARCHAR(500),
    content LONGTEXT,
    post_type VARCHAR(50),
    submolt_id VARCHAR(100),
    submolt_name VARCHAR(255),
    created_at DATETIME NULL,
    updated_at DATETIME NULL,
    comment_count INT NULL,
    verification_status VARCHAR(100),
    is_deleted BOOLEAN NULL,
    is_spam BOOLEAN NULL,
    raw_json JSON NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_posts_author (author_id),
    INDEX idx_posts_created (created_at),
    INDEX idx_posts_submolt (submolt_name)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id VARCHAR(100) PRIMARY KEY,
    post_id VARCHAR(100),
    author_id VARCHAR(100),
    parent_comment_id VARCHAR(100) NULL,
    content LONGTEXT,
    created_at DATETIME NULL,
    updated_at DATETIME NULL,
    reply_count INT NULL,
    depth INT NULL,
    is_deleted BOOLEAN NULL,
    is_spam BOOLEAN NULL,
    raw_json JSON NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_comments_post (post_id),
    INDEX idx_comments_author (author_id),
    INDEX idx_comments_created (created_at),
    INDEX idx_comments_parent (parent_comment_id)
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    started_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    posts_collected INT DEFAULT 0,
    accounts_collected INT DEFAULT 0,
    comments_collected INT DEFAULT 0,
    status VARCHAR(30) NOT NULL,
    notes TEXT
);

