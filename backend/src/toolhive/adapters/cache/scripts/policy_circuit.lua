local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local key, op, nonce = KEYS[1], ARGV[1], ARGV[2]
local state = redis.call('HGET', key, 'state') or 'closed'
local generation = redis.call('HGET', key, 'generation')
if not generation then
    generation = nonce
    redis.call('HSET', key, 'state', 'closed', 'generation', generation, 'failures', 0)
end
if op == 'allow' then
    if state == 'closed' then return {1, generation, ''} end
    local until_time = tonumber(redis.call('HGET', key, state == 'open' and 'open_until' or 'probe_until') or '0')
    if until_time > now then return {0, generation, ''} end
    redis.call('HSET', key, 'state', 'probe', 'generation', nonce, 'owner', nonce,
        'probe_until', now + tonumber(ARGV[6]))
    return {1, nonce, nonce}
end
if generation ~= ARGV[7] then return {0} end
if state == 'probe' then
    if redis.call('HGET', key, 'owner') ~= ARGV[8] or tonumber(redis.call('HGET', key, 'probe_until')) <= now then return {0} end
    if op == 'success' then
        redis.call('HSET', key, 'state', 'closed', 'generation', nonce, 'failures', 0)
    else
        redis.call('HSET', key, 'state', 'open', 'generation', nonce,
            'open_until', op == 'abandon' and now or now + tonumber(ARGV[5]))
    end
    return {1}
end
if state ~= 'closed' or op == 'abandon' then return {0} end
if op == 'success' then
    redis.call('HSET', key, 'failures', 0)
    return {1}
end
local window = tonumber(redis.call('HGET', key, 'window_until') or '0')
if window <= now then
    redis.call('HSET', key, 'failures', 0, 'window_until', now + tonumber(ARGV[4]))
end
local failures = redis.call('HINCRBY', key, 'failures', 1)
if failures >= tonumber(ARGV[3]) then
    redis.call('HSET', key, 'state', 'open', 'generation', nonce, 'open_until', now + tonumber(ARGV[5]))
end
return {1}
