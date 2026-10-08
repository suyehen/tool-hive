# ToolHive 后端

当前已实现 A/B 基础设施及 C 领域模块：16 张表的 ORM 与首个迁移、Principal/API Key、
工具版本审批与通道发布、Provider 配置治理、凭据掩码查询/吊销、Grant 范围解析。
执行内核、检索及管理 CLI 继续按 docs/02 推进。

Python 3.12+；在 backend 目录执行：

```powershell
python -m pip install -e ".[dev]"
python scripts/verify.py --no-config
python scripts/regression.py
python scripts/domain_regression.py
```

regression 使用本地内存数据库、模拟 HTTP 与假 Redis，不读取 .env、不访问外部服务。
scripts/selfcheck.py 会读 .env 并写数据库/Redis，只用于明确授权的隔离验证环境。

真实基础设施验证是独立的 integration 阶段，默认显示 SKIP，本地 PASS 不代表集成通过。
准备隔离环境配置后执行：

```powershell
python scripts/verify.py --no-config --integration-env .env.test
```

该阶段先运行 `selfcheck.py --strict --env-file .env.test` 验证真实 PostgreSQL/Redis，
再运行 `domain_selfcheck.py --env-file .env.test` 验证 C 的迁移、仓储、状态机与并发审批。
连接失败导致跳过时也返回非零码；配置文件缺失直接失败，绝不回退到默认 .env。
它会创建并清理本次专用临时表、缓存键与随机 `th_c_selfcheck_*` schema。
领域检查要求 vector/pg_trgm 已安装，不修改共享扩展或已有业务表。

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
目前没有可运行的 toolhive CLI 或 Web 服务入口。

## C 模块的使用与核对

领域模型入口为 `toolhive.core.domain.models`。写入服务由调用方先开启
`async with session.begin()`，服务内部使用 savepoint，既不提交外层事务，也不关闭 session。
传入持有租约的 `SnowflakeGenerator.next_id`；验证脚本的顺序 ID 仅用于隔离样例。
API Key 明文仅在 `IdentityService.issue_key` 返回的对象中出现，repr 不显示明文。
Credential 管理查询只返回掩码；运行面读取密文不等同于解密权限。
HTTP 方法只提供导入建议，最终执行与重试语义使用已审核的版本字段。

`CatalogService` 提供创建工具/草稿、修订、送审、审批、驳回重开、通道切换及工具启停。
首次审批发布原子创建 stable、更新生产投影并写索引/权限失效 Outbox；后续审批不自动切换 stable。
冻结定义与历史记录不允许 ORM 批量改写；JSON 嵌套修改也在提交前检查。
直接 SQL 是受信任数据库运维能力，不作为领域写入接口。
权限失效消费与可见缓存由 D 提供；索引构建和通用 Outbox 调度尚由 H 实现。

仅在准备好的空应用库运行以下命令（不会自动在现有业务库迁移）：

```powershell
python -m alembic upgrade head --sql   # 只导出 SQL，读取数据库配置，不连接服务
python -m alembic upgrade head         # 实际建表；需要扩展安装权限或扩展已安装
python -m alembic check                # C2：人工确认数据库与 ORM 无待迁移差异
```

已按历史 DDL 手工建表的库不能直接当作空库执行首个迁移；先人工核对 schema，
确认完全匹配后再决定是否 stamp，禁止自动 stamp 或覆盖既有数据。

C2 的核对记录：2026-10-07，真实 PostgreSQL 随机隔离 schema 验证 16 张表，
Alembic compare_metadata（含类型、默认值）无差异，全部索引一致；并发审批恰好一个成功；
迁移 downgrade 删除全部领域表，最后清理测试 schema。可按以下命令复验：

```powershell
python scripts/domain_selfcheck.py --env-file .env.test
```

人工核对列定义与索引时使用以下只读 SQL；schema 参数替换为目标环境的实际 schema：

```sql
SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = '<schema>' ORDER BY table_name, ordinal_position;
SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname = '<schema>' ORDER BY tablename, indexname;
```

## D 模块的使用与核对

`AuthorizationService.resolve` 使用新鲜数据库授权；幂等 lookup 指纹匹配后用
`pinned_version_id` 固定历史版本重新授权。执行授权使用独立、干净的读取 session，
不与未提交的管理写入共用身份映射。`visible_ids` 是缓存候选集合，
检索排序前通过 `filter_discoverable` 叠加当前状态、版本范围、IP/时间约束。
缓存 TTL 至多 60 秒；`consume_invalidations` 在短事务中消费权限 Outbox，事务由调用方提交。

`ResourcePolicy` 位于 `core/policy/resources.py`，QPS 放在幂等 lookup 前；
每日与并发放在 claim 后。每个匹配 Grant 独立约束，请求被拒绝时补偿已经预留的资源。
每日额度在出站前 `commit_daily`，确定未出站时 `release`；未知结果不能退还。
并发的 `release` 放在 finally。租期覆盖整体 deadline，长期处理由 F 调度 `renew`。
`CircuitPolicy` 位于 `core/policy/circuit.py`，阈值、窗口、打开时长、探针租期可配置。

`IdempotencyPolicy` 提供 lookup/claim/replay、owner CAS 状态迁移和结果缓存。
F 在全部出站前检查成功后调用 `transition(record, "dispatch")`；结果不确定时转 unknown，
即使处理租约过期也不得再次出站。completed 保存原 trace_id、版本与结果；
超过 256 KiB 的结果不保留正文，重放仍返回首次结果元数据。M0 确认只判定并拒绝，令牌属 M1。
共享错误目录 `core/errors.py` 供 D/F 使用，协议状态映射仍由 I 处理。

```powershell
python scripts/policy_regression.py                       # 不依赖外部服务
python scripts/policy_lua_regression.py                   # 可选 fakeredis[lua] 验证
python scripts/policy_selfcheck.py --env-file .env.test    # 严格真实集成，随机 schema / key 后清理
python scripts/verify.py --no-config --integration-env .env.test
```

2026-10-08：离线契约、类型和内存 Lua 竞争验证通过；真实数据库/Redis 连接被拒绝，
真实集成尚未通过。内存验证不替代集成验收；verify 的 integration 必须显式选配置，
依赖不可达或断言失败会返回非零码。
