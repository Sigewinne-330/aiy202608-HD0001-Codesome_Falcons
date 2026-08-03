-- 为现有 tasks 表增加待办/流程任务类型及最终节点标记。
ALTER TABLE tasks
    ADD COLUMN task_type ENUM('todo','process') NOT NULL DEFAULT 'todo' AFTER parent_id,
    ADD COLUMN is_final BOOLEAN NOT NULL DEFAULT FALSE AFTER task_type;

-- 已经拥有子任务的顶层任务按流程任务处理，避免主任务继续出现在日历中。
UPDATE tasks AS parent
JOIN (
    SELECT DISTINCT parent_id
    FROM tasks
    WHERE parent_id IS NOT NULL
) AS child_ids ON child_ids.parent_id = parent.id
SET parent.task_type = 'process'
WHERE parent.parent_id IS NULL;
