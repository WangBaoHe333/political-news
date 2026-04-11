-- Postgres 容器首次初始化时执行；表结构由应用 init_db() 创建。
-- 保留此文件以便 docker-compose.prod.yml 挂载路径存在。
SELECT 1;
