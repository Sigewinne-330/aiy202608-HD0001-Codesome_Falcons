CREATE DATABASE IF NOT EXISTS ib_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE ib_assistant;

CREATE TABLE IF NOT EXISTS `user` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    nickname VARCHAR(100) DEFAULT NULL,
    password VARCHAR(255) NOT NULL,
    grade VARCHAR(50) DEFAULT NULL COMMENT '用户等级/年级',
    register_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    email VARCHAR(100) DEFAULT NULL,
    phone_number VARCHAR(20) DEFAULT NULL,
    wechat_id VARCHAR(50) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    task_type ENUM('todo','process') NOT NULL DEFAULT 'todo',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    subject VARCHAR(100),
    priority ENUM('low','medium','high','urgent') DEFAULT 'medium',
    status ENUM('todo','in_progress','done','overdue') DEFAULT 'todo',
    deadline DATE,
    estimated_hours DECIMAL(5,1) DEFAULT 0,
    progress INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS deadlines (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    source VARCHAR(100),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    due_date DATE NOT NULL,
    subject VARCHAR(100),
    priority ENUM('low','medium','high','urgent') DEFAULT 'medium',
    status ENUM('pending','done','overdue') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    role ENUM('user','assistant','system') NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO `user` (id, username, password, email) VALUES
(1, 'demo', '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxSgHBkdBVhFqGQmHNpJtOZqG6tFhq', 'demo@ibstudent.com');
