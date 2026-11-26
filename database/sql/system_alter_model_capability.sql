-- ============================================================
-- 存量库迁移: 移除多模态角色 + 模型能力键(视觉开关/最大输出)
--
-- 背景:
--   visual(多模态) 角色并入 chat：删除角色卡片与字典项，原多模态调用改用 chat；
--   chat/rewrite 的能力键落 sys_model_config.extra：
--     vision(bool)         是否支持图片输入
--     max_output(string)  单次请求最大输出 token（字典 model_max_output 档位；
--                         未配置时取该字典第一项，sort_order 升序）
--   全局标量 CHAT_MAX_OUTPUT_TOKENS 删除，改由各模型 extra.max_output 决定。
--
-- 幂等: 可重复执行; 仅清理该角色/参数键, 不触碰其它模型配置与业务数据。
-- ============================================================

-- 1. 删除多模态角色: 字典项 + 配置行
delete from sys.sys_dict_data
where dict_type = 'model_types' and value = 'visual';

delete from sys.sys_model_config where role = 'visual';

-- 2. 删除全局对话输出上限参数（输出上限改为每模型 extra.max_output）
delete from sys.sys_config where key = 'CHAT_MAX_OUTPUT_TOKENS';

-- 3. 新增最大输出档位字典（前端「模型管理」下拉数据源）
insert into sys.sys_dict_type (id, name, type, status, remark, created_at, updated_at)
values (
    '01a0f1e2-0001-7000-8000-000000000601',
    '模型最大输出', 'model_max_output', 'active',
    '对话/改写压缩模型单次请求最大输出档位(extra.max_output)',
    now(), now()
)
on conflict (type) do nothing;

-- 3.1 清理旧版脚本误插的自造档位（仅限本脚本历史固定 id；人工维护的档位不受影响）
delete from sys.sys_dict_data
where dict_type = 'model_max_output'
  and id in (
      '01a0f1e2-0002-7000-8000-000000000703',
      '01a0f1e2-0002-7000-8000-000000000704',
      '01a0f1e2-0002-7000-8000-000000000705'
  );

-- 旧版 4K/8K 若已按固定 id 写入，纠正为 128K/384K（仅当值仍是旧值时才更新）
update sys.sys_dict_data
set label = '128K', value = '128000', sort_order = 0, is_default = true,
    remark = '单次请求最大输出 128000 token(默认)', updated_at = now()
where id = '01a0f1e2-0002-7000-8000-000000000701'
  and dict_type = 'model_max_output' and value = '4096';

update sys.sys_dict_data
set label = '384K', value = '384000', sort_order = 1, is_default = false,
    remark = '单次请求最大输出 384000 token', updated_at = now()
where id = '01a0f1e2-0002-7000-8000-000000000702'
  and dict_type = 'model_max_output' and value = '8192';

-- 3.2 仅在字典尚无任何档位时补默认档位；已自行维护过 model_max_output 的库不重复插入
insert into sys.sys_dict_data (id, dict_type, label, value, sort_order, is_default, status, remark, created_at, updated_at)
select * from (values
    ('01a0f1e2-0002-7000-8000-000000000701'::uuid, 'model_max_output', '128K', '128000', 0, true,  'active', '单次请求最大输出 128000 token(默认)', now(), now()),
    ('01a0f1e2-0002-7000-8000-000000000702'::uuid, 'model_max_output', '384K', '384000', 1, false, 'active', '单次请求最大输出 384000 token', now(), now())
) as v(id, dict_type, label, value, sort_order, is_default, status, remark, created_at, updated_at)
where not exists (
    select 1 from sys.sys_dict_data where dict_type = 'model_max_output'
);

-- 4. chat/rewrite 补齐能力键（已有值优先，不覆盖人工配置；非对象 JSON 归一为空对象）
--    不写入 max_output：未配置时由后端取字典 model_max_output 第一项作为缺省
update sys.sys_model_config
set extra = '{"vision": false}'::jsonb
            || case when jsonb_typeof(extra) = 'object' then extra else '{}'::jsonb end,
    updated_at = now()
where role in ('chat', 'rewrite');