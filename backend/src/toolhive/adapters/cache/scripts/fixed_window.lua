-- 固定窗口计数 —— 用于**自然日配额**（设计 §9.1 配额语义）
--
-- 为什么需要它：设计明确"配额按**自然日**计"，而幂等按 **24h 滑窗**计，两者互不相干
-- （§7.2 幂等保留期一行）。自然日是一个**日历对齐**的固定窗口，用滑动窗口脚本表达不了。
--
-- 窗口对齐由**调用方**负责：
--   * key 里带上日期，例如 quota:{pid}:tool:{code}:daily:20261005
--   * expire_at 传"该自然日结束"的绝对 Unix 秒（次日 00:00:00）
-- 这样跨日时 key 自然换新，无需清理任务。
--
-- KEYS[1] 计数 key
-- ARGV[1] limit     窗口内允许的最大次数
-- ARGV[2] expire_at 绝对 Unix 秒（仅在本窗口第一次计数时设置）
--
-- 返回 {allowed, count}
--
-- INCR 与 EXPIREAT 必须在同一个脚本里：分两条命令发会有竞态——若进程在
-- INCR 之后、EXPIREAT 之前崩掉，这个 key 就永远不会过期，配额会被永久占死。

local key = KEYS[1]
local limit = tonumber(ARGV[1])
local expire_at = tonumber(ARGV[2])

local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIREAT', key, expire_at)
end

local allowed = 0
if count <= limit then
    allowed = 1
end

return { allowed, count }
