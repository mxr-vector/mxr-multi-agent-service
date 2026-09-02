--
-- TOC entry 5157 (class 0 OID 24906)
-- Dependencies: 224
-- Data for Name: sys_config; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_config (id, name, key, value, is_builtin, remark, created_at, updated_at)
values  ('019fb5e7-d9cf-7066-a0a5-8b34a8c077fb', '重排序最终候选数', 'RAG_FINAL_TOP_K', '5', true, '重排序后保留的最终候选数量(top-k)', '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:01:38.510209 +00:00'),
        ('019fb5e7-d9cf-7087-a5f4-8ea3b049c9e7', '反思检索轮数上限', 'RAG_REFLECT_ROUND_CAP', '3', true, '反思循环最大检索轮数上限', '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:01:38.510209 +00:00'),
        ('019fb5e7-d9cf-7095-a47b-946fe95b3005', 'checkpoint 保留天数', 'CHAT_CHECKPOINT_TTL_DAYS', '7', true, 'LangGraph checkpoint 保留天数, 超期由后台任务清理', '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:01:38.510209 +00:00'),
        ('019fb5e7-d9cf-70a5-8ed2-277056efad89', '回落历史消息条数上限', 'CHAT_HISTORY_MAX_MESSAGES', '20', true, 'checkpoint 缺失时 condense 回落业务表读取的历史消息条数上限', '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:01:38.510209 +00:00'),
        ('019fb5e7-d9ce-7e12-b5d9-db5c8d82bcf5', '混合召回候选池大小', 'RAG_CANDIDATE_POOL_SIZE', '50', true, '混合召回(dense+sparse RRF 融合)后保留的候选池上限', '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:35:31.152852 +00:00'),
        ('019fb6c6-95ca-7c4e-a8fe-e99080f18e5a', '自托管DrawIO服务地址', 'DRAWIO_EMBED_URL', 'http://127.0.0.1:8080', true, '绘图设计 自托管DrawIO服务地址', '2026-07-31 06:04:55.622975 +00:00', '2026-07-31 06:05:09.561572 +00:00'),
        ('019ff44c-8950-7422-9d2c-fe4c49ea7285', '对话输出token上限', 'CHAT_MAX_OUTPUT_TOKENS', '8192', true, '对话模型请求的输出上限(max_tokens)，参与输入预算计算(输入预算=context_window-max_output_tokens-10%边际)', '2026-08-12 04:51:14.171808 +00:00', '2026-08-12 04:59:25.105785 +00:00'),
        ('01a0b1c2-0001-7000-8000-000000000101', '多跳检索最大跳数', 'RAG_MAX_HOPS', '2', true, '受控多跳证据检索的最大跳数(含原问题首跳)', '2026-08-18 06:00:00 +00:00', '2026-08-18 06:00:00 +00:00'),
        ('01a0b1c2-0001-7000-8000-000000000102', '多跳每跳候选池大小', 'RAG_HOP_POOL_SIZE', '20', true, '多跳检索每一跳独立召回+rerank 的候选池上限', '2026-08-18 06:00:00 +00:00', '2026-08-18 06:00:00 +00:00'),
        ('01a0b1c2-0001-7000-8000-000000000104', '多跳合并池大小', 'RAG_MULTIHOP_MERGE_POOL', '30', true, '逐跳候选汇入合并池的文档数上限，终排对原问题统一重排后截取 top-k', '2026-08-21 06:00:00 +00:00', '2026-08-21 06:00:00 +00:00'),
        ('01a0b1c2-0001-7000-8000-000000000105', '通用实体文档频率阈值(%)', 'ENTITY_GENERIC_DF_PERCENT', '5', true, '实体覆盖文档占比超过该阈值(%)即视为通用实体，不进实体扩展候选（统计判据，非词表）', '2026-08-22 06:00:00 +00:00', '2026-08-22 06:00:00 +00:00');

--
-- TOC entry 5158 (class 0 OID 24925)
-- Dependencies: 225
-- Data for Name: sys_dept; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_dept (id, parent_id, name, sort_order, leader, status, created_at, updated_at)
values  ('019fa265-8a56-7fce-b72a-344fe2f8ec87', null, '总部', 0, null, 'active', '2026-07-27 07:06:31.382400 +00:00', '2026-07-27 07:06:31.382400 +00:00'),
        ('019fa265-8a60-7d41-9e4e-af23b2a6beab', '019fa265-8a56-7fce-b72a-344fe2f8ec87', '研发部', 0, null, 'active', '2026-07-27 07:06:31.391176 +00:00', '2026-07-27 07:06:31.391176 +00:00'),
        ('019fa265-8a66-7b6e-a330-46a028be8e37', '019fa265-8a56-7fce-b72a-344fe2f8ec87', '市场部', 0, null, 'active', '2026-07-27 07:06:31.397823 +00:00', '2026-07-27 07:06:31.397823 +00:00');


--
-- TOC entry 5156 (class 0 OID 24883)
-- Dependencies: 223
-- Data for Name: sys_dict_data; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_dict_data (id, dict_type, label, value, sort_order, is_default, status, remark, created_at, updated_at)
values  ('019fa7b2-986d-7df1-a85a-5b17bb62acc7', 'visibility_type', '私有', 'private', 0, true, 'active', null, '2026-07-28 07:48:47.339482 +00:00', '2026-07-28 07:48:51.075894 +00:00'),
        ('019fa7b2-cfe7-7016-96ee-4d574ec8ece2', 'visibility_type', '部门', 'department', 1, false, 'active', null, '2026-07-28 07:49:01.541264 +00:00', '2026-07-28 07:49:11.114857 +00:00'),
        ('019fa7b3-29b6-7248-a609-6bd4eec82fc0', 'visibility_type', '公开', 'public', 2, false, 'active', null, '2026-07-28 07:49:24.532000 +00:00', '2026-07-28 07:49:24.532000 +00:00'),
        ('019fa7b4-0cf5-7eee-ba8b-7cdfef75cc4d', 'status', '激活', 'active', 0, true, 'active', null, '2026-07-28 07:50:22.708511 +00:00', '2026-07-28 07:50:22.708511 +00:00'),
        ('019fa7b4-5605-7687-912f-b7a7041fb142', 'status', '已归档', 'archived', 1, false, 'active', null, '2026-07-28 07:50:41.411415 +00:00', '2026-07-28 07:50:41.411415 +00:00'),
        ('019fa7b4-872c-71c5-b978-39e39c3b15a6', 'status', '已删除', 'deleted', 2, false, 'active', null, '2026-07-28 07:50:53.994785 +00:00', '2026-07-28 07:50:53.994785 +00:00'),
        ('019fac76-1e71-7d2e-8213-9f30a6681641', 'reasoning_effort', '最低限度', 'minimal', 1, false, 'active', null, '2026-07-29 06:00:50.031848 +00:00', '2026-07-29 06:44:18.929063 +00:00'),
        ('019fac76-5be6-7d29-b6ed-b597e457be7f', 'reasoning_effort', '中', 'medium', 2, false, 'active', null, '2026-07-29 06:01:05.764394 +00:00', '2026-07-29 06:44:23.170003 +00:00'),
        ('019fac76-40e6-7aba-841c-abcba09e86e1', 'reasoning_effort', '低', 'low', 3, false, 'active', null, '2026-07-29 06:00:58.853115 +00:00', '2026-07-29 06:44:31.659777 +00:00'),
        ('019fac76-7b3c-7684-b4ab-2ab06ac2c335', 'reasoning_effort', '高', 'high', 4, false, 'active', null, '2026-07-29 06:01:13.787067 +00:00', '2026-07-29 06:44:34.258149 +00:00'),
        ('019fac9d-bc25-7f17-a1a7-116b35588dfa', 'reasoning_effort', '关闭', 'off', 0, true, 'active', null, '2026-07-29 06:44:06.306795 +00:00', '2026-07-29 07:12:23.958277 +00:00'),
        ('019fb76a-ecd2-7ee8-8b7f-4e392fa78bf7', 'context_window', '200K', '200000', 0, true, 'active', null, '2026-07-31 09:04:25.807689 +00:00', '2026-07-31 09:21:50.178014 +00:00'),
        ('019fb76b-3440-7e43-a53d-72e96cc30b19', 'context_window', '400K', '400000', 0, false, 'active', null, '2026-07-31 09:04:44.095223 +00:00', '2026-07-31 09:21:50.178014 +00:00'),
        ('019fb76b-6c89-7fa2-aa1a-d42e7304d76d', 'context_window', '1M', '1000000', 0, false, 'active', null, '2026-07-31 09:04:58.504622 +00:00', '2026-07-31 09:21:50.178014 +00:00'),
        ('019fd72f-efe4-75c4-a936-f14fc1afd2e1', 'embedding_provider', 'cohere', 'cohere', 0, true, 'active', null, '2026-08-06 13:07:50.861090 +00:00', '2026-08-06 13:07:50.861090 +00:00'),
        ('019fd730-0e80-7986-9491-e6aafe481daa', 'embedding_provider', 'openai', 'openai', 1, false, 'active', null, '2026-08-06 13:07:58.642348 +00:00', '2026-08-06 13:07:58.642348 +00:00'),
        ('019fd730-32a1-75c8-9aff-27b5905a0bc4', 'embedding_provider', 'dashscope', 'dashscope', 2, false, 'active', null, '2026-08-06 13:08:07.961371 +00:00', '2026-08-06 13:08:07.961371 +00:00'),
        ('019fd758-16cb-7158-aab8-c0782ce7aecd', 'sse_event', 'sources', 'sources', 0, false, 'active', '引用', '2026-08-06 13:51:42.262410 +00:00', '2026-08-06 13:51:42.262410 +00:00'),
        ('019fd758-3ca7-78d2-bbb1-0b13e5520393', 'sse_event', 'done', 'done', 0, false, 'active', '结束', '2026-08-06 13:51:51.888167 +00:00', '2026-08-06 13:51:51.888167 +00:00'),
        ('019fd757-dd27-7653-819f-19c03bfed40a', 'sse_event', 'answer', 'answer', 0, false, 'active', '回复', '2026-08-06 13:51:27.516460 +00:00', '2026-08-06 13:51:58.637801 +00:00'),
        ('019fd757-b506-7f8f-8787-826083ec4b8d', 'sse_event', 'think', 'think', 0, false, 'active', '思考内容', '2026-08-06 13:51:17.071646 +00:00', '2026-08-06 13:52:24.121657 +00:00'),
        ('019fd758-df5f-7fc8-ad10-66385ad25ff3', 'sse_event', 'error', 'error', 0, false, 'active', '错误', '2026-08-06 13:52:33.565457 +00:00', '2026-08-06 13:52:33.565457 +00:00'),
        ('019fd75a-69ca-7385-b0a8-049f8c538112', 'sse_event', 'feed', 'feed', 0, false, 'active', '追问', '2026-08-06 13:54:14.532092 +00:00', '2026-08-06 13:54:14.532092 +00:00'),
        ('019feef7-e14e-7ab9-824b-b6a626d881f0', 'chunk_strategy', '通用标点分块', 'char', 0, true, 'active', null, '2026-08-11 03:57:30.313879 +00:00', '2026-08-11 03:58:47.340032 +00:00'),
        ('019feef8-848a-7137-8b25-611cd525a44f', 'chunk_strategy', '语义分块', 'semantic', 1, false, 'active', null, '2026-08-11 03:58:12.101374 +00:00', '2026-08-11 03:58:55.851215 +00:00'),
        ('019feef8-2bba-7798-8a9e-4ce26330f3dc', 'chunk_strategy', '章节分块', 'structure', 2, false, 'active', null, '2026-08-11 03:57:49.366409 +00:00', '2026-08-11 03:59:03.106178 +00:00'),
        ('019ff51b-a877-7050-9a89-071848846524', 'model_types', '多模态模型', 'visual', 0, false, 'active', null, '2026-08-12 08:34:18.354118 +00:00', '2026-08-12 08:34:18.354118 +00:00'),
        ('019ff51b-e3db-7403-b0bf-0361e29b02cb', 'model_types', '改写压缩模型', 'rewrite', 0, false, 'active', null, '2026-08-12 08:34:33.560087 +00:00', '2026-08-12 08:34:33.560087 +00:00'),
        ('019ff51c-0b09-7fa3-922a-505e47e46b25', 'model_types', '重排序模型', 'rerank', 0, false, 'active', null, '2026-08-12 08:34:43.591282 +00:00', '2026-08-12 08:34:43.591282 +00:00'),
        ('019ff51c-5213-7066-b6b6-bfe458a3e661', 'model_types', '对话模型', 'chat', 0, false, 'active', null, '2026-08-12 08:35:01.775117 +00:00', '2026-08-12 08:35:01.775117 +00:00'),
        ('019ff51c-80cc-77a7-a1bb-312c812aa084', 'model_types', '图像模型', 'image', 0, false, 'active', null, '2026-08-12 08:35:13.737118 +00:00', '2026-08-12 08:35:13.737118 +00:00');
--
-- TOC entry 5155 (class 0 OID 24864)
-- Dependencies: 222
-- Data for Name: sys_dict_type; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_dict_type (id, name, type, status, remark, created_at, updated_at)
values  ('019fa7b2-6490-7587-982f-6b4d9d4f5c21', '可见性', 'visibility_type', 'active', null, '2026-07-28 07:48:34.061154 +00:00', '2026-07-28 07:48:34.061154 +00:00'),
        ('019fa7b3-9a9c-7ed3-aabb-434e923e09c9', '进度状态', 'status', 'active', null, '2026-07-28 07:49:53.435767 +00:00', '2026-07-28 07:49:53.435767 +00:00'),
        ('019fac75-7289-711f-a290-7ca04cfedfb5', '推理等级', 'reasoning_effort', 'active', null, '2026-07-29 06:00:06.022149 +00:00', '2026-07-29 06:00:06.022149 +00:00'),
        ('019fb769-bd93-707d-8246-edec3110ab27', '模型上下文窗口', 'context_window', 'active', null, '2026-07-31 09:03:08.176120 +00:00', '2026-07-31 09:21:50.180896 +00:00'),
        ('019fd72f-7363-7768-8fc9-79e7d2bb291b', '嵌入模型协议', 'embedding_provider', 'active', null, '2026-08-06 13:07:18.399232 +00:00', '2026-08-06 13:07:18.399232 +00:00'),
        ('019fd757-6342-7eee-b1f9-2faf833db3d8', 'SSE事件', 'sse_event', 'active', null, '2026-08-06 13:50:56.284259 +00:00', '2026-08-06 13:50:56.284259 +00:00'),
        ('019feef7-72bb-7615-a9aa-64f7ec5974aa', 'chunk策略', 'chunk_strategy', 'active', null, '2026-08-11 03:57:02.008430 +00:00', '2026-08-11 03:57:02.008430 +00:00'),
        ('019ff51b-37c3-7fb6-8318-ea2441ddabe8', '模型分类', 'model_types', 'active', null, '2026-08-12 08:33:49.501893 +00:00', '2026-08-12 08:33:49.501893 +00:00');

--
-- TOC entry 5161 (class 0 OID 24985)
-- Dependencies: 228
-- Data for Name: sys_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_menu (id, parent_id, menu_type, name, path, component, label, icon, perms, visible, sort_order, status, created_at, updated_at)
values  ('01900000-0000-7000-8000-000000000002', '01900000-0000-7000-8000-000000000001', 'menu', 'system-user', '/system/user', 'system-user', '用户管理', 'user', null, true, 1, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000003', '01900000-0000-7000-8000-000000000001', 'menu', 'system-role', '/system/role', 'system-role', '角色管理', 'role', null, true, 2, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000004', '01900000-0000-7000-8000-000000000001', 'menu', 'system-dept', '/system/dept', 'system-dept', '部门管理', 'dept', null, true, 3, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000005', '01900000-0000-7000-8000-000000000001', 'menu', 'system-menu', '/system/menu', 'system-menu', '菜单管理', 'menu', null, true, 4, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000006', '01900000-0000-7000-8000-000000000001', 'menu', 'system-dict', '/system/dict', 'system-dict', '字典管理', 'dict', null, true, 5, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000007', '01900000-0000-7000-8000-000000000001', 'menu', 'system-config', '/system/config', 'system-config', '参数管理', 'config', null, true, 6, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 05:30:44.428008 +00:00'),
        ('01900000-0000-7000-8000-000000000001', null, 'dir', 'system', '/system', null, '系统管理', 'settings', null, true, 0, 'active', '2026-07-27 05:30:44.428008 +00:00', '2026-07-27 07:55:59.920293 +00:00'),
        ('019fa2bd-1633-7227-9b62-33848c740ca0', null, 'dir', null, '/agents', null, '智能体', '智能优化', null, true, 1, 'active', '2026-07-27 08:42:08.818006 +00:00', '2026-07-27 09:17:05.654201 +00:00'),
        ('019fa292-b518-785e-9422-262b2239df5b', null, 'dir', null, '/rag', null, 'RAG系统', 'touzijihuaguanli', null, true, 2, 'active', '2026-07-27 07:55:51.447521 +00:00', '2026-07-27 09:17:16.234366 +00:00'),
        ('019fa2c4-50f2-7b8a-b703-94abbe1b4f31', null, 'dir', null, '/draw-design', null, '绘制设计', 'bangongyongpinguanli', null, true, 3, 'active', '2026-07-27 08:50:02.610325 +00:00', '2026-07-30 07:36:20.128489 +00:00'),
        ('019fb5b4-95df-77b1-b163-3ab3d460d9e6', '01900000-0000-7000-8000-000000000001', 'menu', 'model-cfg', '/system/model-cfg', 'system-model', '模型管理', 'Cpu', null, true, 0, 'active', '2026-07-31 01:05:38.778801 +00:00', '2026-07-31 02:22:43.617695 +00:00'),
        ('019fa2bc-83fe-7016-a522-505abbdaf2f4', null, 'dir', null, '/story', null, '剧本生成', 'rizhiguanli', null, true, 4, 'active', '2026-07-27 08:41:31.389499 +00:00', '2026-08-12 09:17:42.123728 +00:00'),
        ('019fa2b2-144f-7b3d-9764-178f22b49ae5', '019fa292-b518-785e-9422-262b2239df5b', 'menu', 'knowledge-base', '/rag/knowledgebase/index', 'rag-knowledge-base', 'AI知识库管理', 'Management', null, true, 0, 'active', '2026-07-27 08:30:07.436885 +00:00', '2026-08-13 00:54:17.679585 +00:00'),
        ('019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56', '019fa292-b518-785e-9422-262b2239df5b', 'menu', 'document', '/rag/document/index', 'rag-document', '文档管理', 'List', null, true, 1, 'active', '2026-07-27 08:31:34.972524 +00:00', '2026-08-13 00:54:25.239195 +00:00'),
        ('01900000-0000-7000-8000-000000000008', '019fa2c4-50f2-7b8a-b703-94abbe1b4f31', 'menu', 'draw', '/draw-design/draw/index', 'draw', 'AI 绘图', 'workflow', null, true, 30, 'active', '2026-07-30 07:28:53.757799 +00:00', '2026-08-13 00:54:59.658453 +00:00'),
        ('019ff546-1892-736b-9a18-cf978ef14fcd', '019fa2bc-83fe-7016-a522-505abbdaf2f4', 'menu', 'character', '/story/character/index', 'story-character', '角色库', 'Avatar', null, true, 0, 'active', '2026-08-12 09:20:39.564919 +00:00', '2026-08-31 08:00:00.000000 +00:00'),
        ('019ff89c-62e3-7d54-bf37-6dbfccc66fed', '019fa2bc-83fe-7016-a522-505abbdaf2f4', 'menu', 'projects', '/story/projects/index', 'story-projects', '项目管理', 'Film', null, true, 1, 'active', '2026-08-13 00:53:46.335818 +00:00', '2026-08-31 08:00:00.000000 +00:00');

--
-- TOC entry 5164 (class 0 OID 41516)
-- Dependencies: 244
-- Data for Name: sys_model_config; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_model_config (id, role, name, model_name, api_url, api_key, provider, timeout, max_retries, extra, is_builtin, remark, created_at, updated_at, context_window)
values  ('019fb5e7-d9ce-7c78-8917-1e8e5dac84dc', 'visual', '多模态模型', 'glm-5.3-flash', 'https://opencode.ai/zen/go/v1', '95279527', null, 60, 2, null, true, null, '2026-07-31 02:01:38.510209 +00:00', '2026-07-31 02:08:56.096100 +00:00', 200000),
        ('019fb5e7-d9ce-7c24-8853-c06e3c973c8e', 'rewrite', '改写压缩模型', 'glm-5.3-flash', 'https://opencode.ai/zen/go/v1', '95279527', null, null, null, null, true, null, '2026-07-31 02:01:38.510209 +00:00', '2026-08-04 02:53:00.416500 +00:00', 200000),
        ('019fb5e7-d9ce-7c89-9d32-f87aa2af9749', 'rerank', '重排序模型', 'Qwen3-Embedding-4B', 'http://192.168.245.213:9527', '95279527', 'cohere', null, null, null, true, null, '2026-07-31 02:01:38.510209 +00:00', '2026-08-09 10:23:47.546437 +00:00', 200000),
        ('019fb5e7-d9ce-76ec-ac2e-34c3c8a588b7', 'chat', '对话模型', 'deepseek-v4-flash', 'https://api.deepseek.com', '95279527', null, 60, 2, null, true, null, '2026-07-31 02:01:38.510209 +00:00', '2026-08-09 16:01:45.555195 +00:00', 200000),
        ('019ff50f-47ad-767b-98fe-f3fa59f511f1', 'image', '图像模型', 'gpt-image-2', 'https://api.openai.com/v1', '95279527', null, 60, 2, null, true, null, '2026-08-12 08:20:47.149101 +00:00', '2026-08-12 08:29:40.768145 +00:00', 200000);

--
-- TOC entry 5160 (class 0 OID 24962)
-- Dependencies: 227
-- Data for Name: sys_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_role (id, name, role_key, data_scope, sort_order, status, remark, created_at, updated_at)
values  ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '研究员', 'researcher', 'all', 0, 'active', null, '2026-07-27 06:12:03.105254 +00:00', '2026-07-27 06:12:03.105254 +00:00'),
        ('019fa23b-f8b7-7bd3-814d-81334345475f', '助理研究员', 'Assistant-Researcher', 'all', 0, 'active', null, '2026-07-27 06:21:07.123234 +00:00', '2026-07-27 06:21:07.123234 +00:00'),
        ('019fa23c-7523-7770-ab1e-4b56dec4ba07', '研究实习员', 'Research-Intern', 'all', 0, 'active', null, '2026-07-27 06:21:38.978550 +00:00', '2026-07-27 06:21:38.978550 +00:00'),
        ('019fa2ee-842e-794b-bf3b-76fe95c78a83', '管理员', 'admin', 'all', 0, 'active', null, '2026-07-27 09:36:08.236382 +00:00', '2026-07-27 09:36:08.236382 +00:00');

--
-- TOC entry 5163 (class 0 OID 25015)
-- Dependencies: 230
-- Data for Name: sys_role_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_role_menu (role_id, menu_id)
values  ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000002'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000003'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000004'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000005'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000006'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000007'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2bd-1633-7227-9b62-33848c740ca0'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2b2-144f-7b3d-9764-178f22b49ae5'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2bc-83fe-7016-a522-505abbdaf2f4'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000001'),
        ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa292-b518-785e-9422-262b2239df5b');


--
-- TOC entry 5159 (class 0 OID 24942)
-- Dependencies: 226
-- Data for Name: sys_user; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_user (id, username, password, nickname, dept_id, email, phone, avatar, status, remark, created_at, updated_at)
values  ('01900000-0000-7000-8000-0000000000a1', 'admin', '$2b$12$ZDbTEc7fpaM5878wuIBBEeqj0T32LYtLnsCPWRggRtorRlzRdQiuu', '管理员', null, null, null, null, 'active', null, '2026-07-27 05:49:02.394632 +00:00', '2026-07-27 05:49:02.394632 +00:00'),
        ('019fa265-8bb9-7872-97d1-47b9c52897b0', 'yx01', '$2b$12$6GNOCSpacPSyPYVrtL7Hy.rAsYoU4ffgZleheOAHbFVUT/Nkm2joK', '市场一号', '019fa265-8a66-7b6e-a330-46a028be8e37', null, null, null, 'active', null, '2026-07-27 07:06:31.573371 +00:00', '2026-07-27 07:54:04.965226 +00:00'),
        ('019fa265-8b0e-7d2e-90a0-2c6a114bd327', 'yg01', '$2b$12$llx6T92WUUBP6wzuJuqwZebqNJw72LDlM.T2VqUXpdmMis1O.6zEi', '研发一号', '019fa265-8a60-7d41-9e4e-af23b2a6beab', null, null, null, 'active', null, '2026-07-27 07:06:31.403725 +00:00', '2026-07-27 07:54:13.483248 +00:00');

--
-- TOC entry 5162 (class 0 OID 25007)
-- Dependencies: 229
-- Data for Name: sys_user_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

insert into sys.sys_user_role (user_id, role_id)
values  ('019fa265-8b0e-7d2e-90a0-2c6a114bd327', '019fa23b-f8b7-7bd3-814d-81334345475f'),
        ('019fa265-8bb9-7872-97d1-47b9c52897b0', '019fa23c-7523-7770-ab1e-4b56dec4ba07'),
        ('01900000-0000-7000-8000-0000000000a1', '019fa2ee-842e-794b-bf3b-76fe95c78a83');

