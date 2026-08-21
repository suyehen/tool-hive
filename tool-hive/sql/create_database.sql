-- ToolHive 数据库与用户创建模板
--
-- 用途：首次部署时创建应用数据库用户与数据库。
-- init.sql 只负责建表，不创建数据库；本脚本必须在执行 init.sql 之前完成。
--
-- 执行方式（使用 PostgreSQL 超级用户，例如 postgres）：
--   psql -U postgres -f sql/create_database.sql
-- 或登录 psql 后逐条执行。
--
-- 注意：
--   1. CREATE DATABASE 不能在事务/函数中执行，请直接执行以下语句；
--   2. 密码请替换为实际值，并同步配置到应用 .env / production.yaml；
--   3. 已存在同名用户或数据库时会报错，请先确认是否需要重建，避免覆盖已有数据；
--      仅需重置密码时可用：ALTER USER toolhive WITH PASSWORD '新密码';

-- 1) 创建应用用户
CREATE USER toolhive WITH PASSWORD '请改成数据库密码';

-- 2) 创建应用数据库，属主为 toolhive
CREATE DATABASE toolhive OWNER toolhive ENCODING 'UTF8';
