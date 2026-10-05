-- 并发信号量：申请或续租一个槽位（设计 §7.2「并发：Redis 信号量（不是进程内）」）
--
-- **租约式**：每个持有者带一个过期时间，槽位用 zset 的 score 表示。
-- 为什么不用简单的 INCR/DECR 计数器：调用方进程崩溃时来不及归还，
-- 计数器会永久少一个槽位，且没有任何办法自动恢复。租约到期即自动释放。
--
-- KEYS[1] zset key（score = 租约到期时刻，member = 持有者标识）
-- ARGV[1] limit      并发上限
-- ARGV[2] now_ms     当前毫秒时间戳
-- ARGV[3] lease_ms   本次租约时长
-- ARGV[4] holder_id  持有者标识（同一次调用的多个阶段必须用同一个）
--
-- 返回 {acquired, current}
--   acquired 1 = 拿到或续上了槽位，0 = 已达上限且自己不是持有者
--   current  当前有效持有者数（用于观测/日志）
--
-- ⚠️ **"已是持有者"必须先判，不能先判 current < limit。**
--    曾经的写法是先判 `current < limit` 再做 ZADD，这样在**槽位已满**时，
--    持有者的续租会被直接跳过：租约到期后 ZREMRANGEBYSCORE 会把它的槽位回收，
--    而持有者仍以为自己占着 —— **实际并发数于是突破 limit，互斥被击穿**。
--    续租是持有者的固有权利，与槽位是否已满无关。
--
-- ⚠️ 归还（release）是**必须**的，不是可选优化：租约只是崩溃兜底，
--    正常情况下应当在 finally 里显式释放，否则并发额度会被白白占着直到租约到期。

local key = KEYS[1]
local limit = tonumber(ARGV[1])
local now_ms = tonumber(ARGV[2])
local lease_ms = tonumber(ARGV[3])
local holder = ARGV[4]

-- 先清理租约已到期的持有者。这是"崩溃自愈"的关键一步，也必须在判 ZSCORE 之前做，
-- 否则刚过期的自己会被当成"仍然持有"而无法重新申请。
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms)

local current = redis.call('ZCARD', key)
local acquired = 0

if redis.call('ZSCORE', key, holder) then
    -- 已是持有者：只续租，不占新槽位，也不受 limit 约束。
    redis.call('ZADD', key, now_ms + lease_ms, holder)
    acquired = 1
elseif current < limit then
    redis.call('ZADD', key, now_ms + lease_ms, holder)
    current = current + 1
    acquired = 1
end

if current > 0 then
    -- key 的 TTL 只需长到能覆盖最晚到期的那个租约，再留一倍余量。
    redis.call('PEXPIRE', key, lease_ms * 2)
end

return { acquired, current }
