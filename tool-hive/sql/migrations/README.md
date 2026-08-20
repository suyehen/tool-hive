# 数据库增量迁移

本目录存放从 `sql/init.sql` 基线之后的增量迁移脚本。

规则：

- 文件名格式：`<序号>_<描述>.sql`，例如 `001_add_example.sql`；
- 脚本必须幂等（尽量使用 `IF NOT EXISTS` / `IF EXISTS`），同一文件只执行一次；
- 由 `toolhive db migrate` 按文件名顺序执行，未应用的脚本会依次执行并记录到 `schema_migrations` 表；
- 全新环境先执行 `sql/init.sql` 完成基线建表，再执行 `toolhive db migrate`（当前无增量时为无操作）。

当前无增量迁移（全部表结构已包含在 `sql/init.sql`）。
