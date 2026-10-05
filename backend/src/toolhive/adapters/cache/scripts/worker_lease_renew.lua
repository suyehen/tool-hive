-- 雪花 ID 的 worker 租约：续租（设计 §4.4）
--
-- 为什么续租要校验持有者：如果一个实例的租约已经过期、另一个实例用同样的
-- (datacenter, worker) 抢到了，**旧实例的续租绝不能成功**——否则两个实例会同时
-- 认为自己持有租约，然后各自从序列 0 开始发号，产出完全相同的 ID。
--
-- KEYS[1] 租约 key
-- ARGV[1] holder_id（只有当前持有者才能续）
-- ARGV[2] ttl_ms
--
-- 返回 1 = 续租成功（仍持有），0 = 已失去租约

if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return 1
end
return 0
