-- 令牌桶（token bucket）—— 设计 §7.2「配额：Redis + Lua 原子计数（令牌桶/滑动窗口）」
--
-- 用途：QPS 限流。稳态速率 = refill_per_second，允许的突发量 = capacity。
--
-- KEYS[1] 桶 key（命名由调用方决定，见设计 §9.1：
--         quota:{principal_id}:{scope_type}:{scope_value}:{window}）
-- ARGV[1] capacity           桶容量（允许的突发量）
-- ARGV[2] refill_per_second  每秒补充的令牌数（= 稳态 QPS 上限）
-- ARGV[3] now_ms             当前毫秒时间戳
-- ARGV[4] requested          本次要取几个令牌（通常 1）
--
-- 返回 {allowed, tokens_left}
--   allowed     1 = 放行，0 = 超限
--   tokens_left 放行后剩余令牌数（向下取整，仅用于观测/日志）
--
-- ⚠️ 时间由调用方传入而不是脚本内取：一次请求的多个阶段必须共享同一个时间基准，
--    否则会出现"配额用 T1、幂等用 T2"这种难以复现的边界行为。

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])

if tokens == nil then
    -- 首次访问：满桶
    tokens = capacity
    ts = now_ms
end

local elapsed = now_ms - ts
if elapsed < 0 then
    -- 时钟回退。按"不补令牌"处理：绝不因为时间倒退而凭空多发。
    elapsed = 0
end
tokens = math.min(capacity, tokens + (elapsed / 1000.0) * rate)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

-- 用固定小数位写入：Redis 会把 Lua number 转成字符串，
-- 不指定格式时浮点表示可能在不同版本间不一致。
redis.call('HSET', key, 'tokens', string.format('%.6f', tokens), 'ts', tostring(math.max(ts, now_ms)))

-- 空闲桶自动回收。把一桶补满所需时间的 2 倍作为 TTL，
-- 保证长期无人访问的 key 不会永久留在 Redis 里。
if rate > 0 then
    local ttl_ms = math.ceil((capacity / rate) * 1000 * 2)
    if ttl_ms < 1000 then
        ttl_ms = 1000
    end
    redis.call('PEXPIRE', key, ttl_ms)
end

return { allowed, math.floor(tokens) }
