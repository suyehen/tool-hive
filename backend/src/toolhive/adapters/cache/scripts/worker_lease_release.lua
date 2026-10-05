-- 雪花 ID 的 worker 租约：主动释放（设计 §4.4）
--
-- 正常停机时释放，让下一个实例不必等 TTL 到期就能拿到这个 worker 号。
-- 同样要校验持有者：不能把别人（用同一个号成功抢到租约的那个实例）的租约删掉。
--
-- KEYS[1] 租约 key
-- ARGV[1] holder_id
--
-- 返回 1 = 删掉了自己的租约，0 = 租约已不属于自己（或已过期）

if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
