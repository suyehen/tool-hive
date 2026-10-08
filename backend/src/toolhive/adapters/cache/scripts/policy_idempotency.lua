-- Values (including Snowflake IDs and result JSON) remain strings: no Lua JSON rounding.
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local key, op, fp, owner = KEYS[1], ARGV[1], ARGV[2], ARGV[3]
local state = redis.call('HGET', key, 'state')
local function record(status) return {status, redis.call('HGETALL', key)} end
if state == 'dispatching' and tonumber(redis.call('HGET', key, 'lease_until')) <= now then
    state = 'unknown'
    redis.call('HSET', key, 'state', state)
    redis.call('PERSIST', key)
end
if op == 'lookup' then return record(state and 'FOUND' or 'MISSING') end
if state and redis.call('HGET', key, 'fingerprint') ~= fp then return record('REUSED') end
if op == 'claim' then
    if state and (redis.call('HGET', key, 'tool_id') ~= ARGV[6] or redis.call('HGET', key, 'version_id') ~= ARGV[7]) then return record('REUSED') end
    if not state then
        redis.call('HSET', key, 'fingerprint', fp, 'principal_id', ARGV[5],
            'tool_id', ARGV[6], 'version_id', ARGV[7], 'binding_digest', ARGV[8])
    elseif state == 'completed' then return record('COMPLETED')
    elseif state == 'unknown' then return record('UNKNOWN')
    elseif tonumber(redis.call('HGET', key, 'lease_until')) > now then return record('BUSY') end
    redis.call('HSET', key, 'state', 'reserved', 'owner', owner, 'lease_until', now + tonumber(ARGV[4]))
    -- Never expire a dispatched record; reservation cleanup uses owner/lease CAS.
    return record('CLAIMED')
end
if not state or redis.call('HGET', key, 'owner') ~= owner then return record('STALE') end
local live = tonumber(redis.call('HGET', key, 'lease_until')) > now
if op == 'abandon' and state == 'reserved' then redis.call('DEL', key) return {'OK', {}} end
if op == 'reap' and state == 'reserved' and not live then redis.call('DEL', key) return {'OK', {}} end
if op == 'renew' and live and (state == 'reserved' or state == 'dispatching') then
    redis.call('HSET', key, 'lease_until', now + tonumber(ARGV[4]))
    return record('OK')
end
if op == 'dispatch' and state == 'reserved' and live then
    redis.call('HSET', key, 'state', 'dispatching')
    redis.call('PERSIST', key)
    return record('OK')
end
if op == 'unknown' and (state == 'dispatching' or state == 'unknown') then
    redis.call('HSET', key, 'state', 'unknown')
    redis.call('PERSIST', key)
    return record('OK')
end
if op == 'complete' then
    if state == 'completed' then return record('OK') end
    if state == 'dispatching' or state == 'unknown' then
        redis.call('HSET', key, 'state', 'completed', 'payload', ARGV[5])
        redis.call('EXPIRE', key, ARGV[6])
        return record('OK')
    end
end
return record('STALE')
