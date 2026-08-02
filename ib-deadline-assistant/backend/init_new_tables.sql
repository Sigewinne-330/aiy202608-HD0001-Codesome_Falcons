-- =============================================
-- 新增5张表：user / task / sub_task / chat_message / conversation
-- 数据库：ib_assistant
-- =============================================

USE ib_assistant;

-- 注意：`user` 是 MySQL 保留字，用反引号包裹
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


CREATE TABLE IF NOT EXISTS task (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    id_name VARCHAR(255) NOT NULL COMMENT '任务标识/名称',
    deadline DATETIME DEFAULT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending' COMMENT '任务状态',
    personal_deadline DATETIME DEFAULT NULL COMMENT '个人截止时间',
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS sub_task (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    notice_time DATETIME DEFAULT NULL COMMENT '提醒时间',
    level VARCHAR(20) DEFAULT 'medium' COMMENT '优先级/级别',
    status VARCHAR(50) DEFAULT 'pending' COMMENT '子任务状态',
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    notice_method VARCHAR(100) DEFAULT NULL COMMENT '提醒方式',
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS conversation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(255) DEFAULT NULL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS chat_message (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    conversation_id INT NOT NULL,
    content TEXT NOT NULL,
    role VARCHAR(20) NOT NULL COMMENT 'user / assistant / system',
    extra JSON DEFAULT NULL COMMENT '扩展字段',
    token INT DEFAULT 0 COMMENT 'token 消耗数',
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES `user`(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversation(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
