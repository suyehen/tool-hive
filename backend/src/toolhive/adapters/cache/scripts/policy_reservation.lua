-- Redis TIME is authoritative for leases. KEYS: pending ZSET, daily committed HASH.
-- ARGV: operation, owner, limit, lease_ms, key_ttl_ms, daily (0/1).
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local op, owner = ARGV[1], ARGV[2]
local daily = ARGV[6] == '1'
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
local committed = daily and redis.call('HEXISTS', KEYS[2], owner) == 1
if op == 'release' then
    redis.call('ZREM', KEYS[1], owner)
    if committed then
        redis.call('HDEL', KEYS[2], owner)
        redis.call('HINCRBY', KEYS[2], 'used', -1)
    end
    return {1}
end
local exists = redis.call('ZSCORE', KEYS[1], owner)
if op == 'commit' then
    if committed then return {1} end
    if not exists then return {0} end
    redis.call('ZREM', KEYS[1], owner)
    redis.call('HSET', KEYS[2], owner, '1')
    redis.call('HINCRBY', KEYS[2], 'used', 1)
    if redis.call('PTTL', KEYS[2]) < tonumber(ARGV[5]) then redis.call('PEXPIRE', KEYS[2], ARGV[5]) end
    return {1}
end
if committed then return {1} end
if op == 'renew' and not exists then return {0} end
local used = daily and tonumber(redis.call('HGET', KEYS[2], 'used') or '0') or 0
if not exists and used + redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return {0} end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[4]), owner)
if redis.call('PTTL', KEYS[1]) < tonumber(ARGV[5]) then redis.call('PEXPIRE', KEYS[1], ARGV[5]) end
return {1}
