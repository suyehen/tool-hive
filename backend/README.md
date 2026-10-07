# ToolHive 后端

当前交付范围为配置、日志、数据库/Redis 适配、加密、HTTP 客户端与雪花 ID。
领域模型、迁移、执行内核、检索及管理 CLI 仍按 docs/02 的任务清单推进。

Python 3.12+；在 backend 目录执行：

```powershell
python -m pip install -e ".[dev]"
python scripts/verify.py --no-config
python scripts/regression.py
```

regression 使用本地内存数据库、模拟 HTTP 与假 Redis，不读取 .env、不访问外部服务。
scripts/selfcheck.py 会读 .env 并写数据库/Redis，只用于明确授权的隔离验证环境。

真实基础设施验证是独立的 integration 阶段，默认显示 SKIP，本地 PASS 不代表集成通过。
准备隔离环境配置后执行：

```powershell
python scripts/verify.py --no-config --integration-env .env.test
```

该阶段以 `selfcheck.py --strict --env-file .env.test` 验证真实 PostgreSQL/Redis。
连接失败导致跳过时也返回非零码；配置文件缺失直接失败，绝不回退到默认 .env。
它会创建并清理本次专用临时表和缓存键。

仓储读取契约：get_by_id/get_for_update/list_by_ids 都刷新已加载属性，返回当前事务可见状态；
有未 flush 修改时抛 UnflushedChangesError（RepositoryError 子类），不会静默覆盖。
条件 UPDATE 显式同步身份映射；后续 touch 代表另一次修改，会从新版本递增。
touch 的无条件 ORM 更新本身仍不提供乐观锁，竞争写应使用条件 UPDATE 或先加行锁。

日志契约：snapshot.buckets 只包含累计 le_*，含 le_+Inf，最后一项等于 count。
单次日志字段 latency_interval 使用 range_lower_upper_ms；首区间包含 0，
后续区间为 (lower,upper]，溢出为 range_lower_inf_ms。
不再输出 latency_bucket、gt_* 或快照同级的 le_inf；解析端应读取新字段。

可选的 `scripts/redis_regression.py` 使用内存 Redis 执行真实 Lua 源码，覆盖时钟回退、
不同租期、并发容量与脚本重载；在隔离验证环境安装 `.[lua-test]` 后运行。
该验证仍不替代真实 Redis 的网络故障/集群集成测试。

配置入口按进程职责区分：

| 进程 | 加载器 | 要求 |
|---|---|---|
| 执行服务 | load_settings | 全量配置，包括 KEK 与索引配置 |
| 管理 CLI/admin | load_management_settings | 数据库、Redis、worker、日志；不加载 KEK |
| 数据库迁移 | load_database_settings | 只需要 TOOLHIVE_DATABASE_URL |

传入 environ 字典时，它是独立来源，不读取 .env、不修改进程环境。
凭据写入及索引重建的运行面任务接口契约见 docs/01 §10.1。
目前没有可运行的 toolhive CLI 或 Web 服务入口，也没有首个建表迁移。
