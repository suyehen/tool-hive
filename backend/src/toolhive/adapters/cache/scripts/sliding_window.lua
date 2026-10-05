-- 滑动窗口计数 —— 设计 §7.2「配额：Redis + Lua 原子计数（令牌桶/滑动窗口）」
--
-- 用途："最近 N 毫秒内不超过 M 次"。相比固定窗口，它不会在窗口边界处放行 2 倍流量。
--
-- KEYS[1] zset key（score = 请求到达的毫秒时间戳，member = 本次请求的唯一标识）
-- ARGV[1] window_ms  窗口长度（毫秒）
-- ARGV[2] limit      窗口内允许的最大次数
-- ARGV[3] now_ms     当前毫秒时间戳
-- ARGV[4] member     本次请求的唯一标识
--
-- 返回 {allowed, count_in_window}
--
-- ⚠️ member 必须是**每次请求唯一**的值（例如 trace_id）。用固定 member 会让
--    重复调用只更新分数、不增加计数，等于把限流悄悄关掉。

local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local member = ARGV[4]

-- 先把滑出窗口的记录删掉，再计数——顺序不能反，否则会把自己算进去。
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)

local count = redis.call('ZCARD', key)
local allowed = 0
if count < limit then
    redis.call('ZADD', key, now_ms, member)
    count = count + 1
    allowed = 1
end

-- 整个 key 的存活时间不必超过一个窗口。
redis.call('PEXPIRE', key, window_ms)

return { allowed, count }
