--
-- TOC entry 5157 (class 0 OID 24906)
-- Dependencies: 224
-- Data for Name: sys_config; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_config VALUES ('019fb5e7-d9cf-7066-a0a5-8b34a8c077fb', '重排序最终候选数', 'RAG_FINAL_TOP_K', '5', true, '重排序后保留的最终候选数量(top-k)', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:01:38.510209+08');
INSERT INTO sys.sys_config VALUES ('019fb5e7-d9cf-7087-a5f4-8ea3b049c9e7', '反思检索轮数上限', 'RAG_REFLECT_ROUND_CAP', '3', true, '反思循环最大检索轮数上限', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:01:38.510209+08');
INSERT INTO sys.sys_config VALUES ('019fb5e7-d9cf-7095-a47b-946fe95b3005', 'checkpoint 保留天数', 'CHAT_CHECKPOINT_TTL_DAYS', '7', true, 'LangGraph checkpoint 保留天数, 超期由后台任务清理', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:01:38.510209+08');
INSERT INTO sys.sys_config VALUES ('019fb5e7-d9cf-70a5-8ed2-277056efad89', '回落历史消息条数上限', 'CHAT_HISTORY_MAX_MESSAGES', '20', true, 'checkpoint 缺失时 condense 回落业务表读取的历史消息条数上限', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:01:38.510209+08');
INSERT INTO sys.sys_config VALUES ('019fb5e7-d9ce-7e12-b5d9-db5c8d82bcf5', '混合召回候选池大小', 'RAG_CANDIDATE_POOL_SIZE', '50', true, '混合召回(dense+sparse RRF 融合)后保留的候选池上限', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:35:31.152852+08');
INSERT INTO sys.sys_config VALUES ('019fb6c6-95ca-7c4e-a8fe-e99080f18e5a', '自托管DrawIO服务地址', 'DRAWIO_EMBED_URL', 'http://127.0.0.1:8080', true, '绘图设计 自托管DrawIO服务地址', '2026-07-31 10:01:38.510209+08', '2026-07-31 10:35:31.152852+08');


--
-- TOC entry 5158 (class 0 OID 24925)
-- Dependencies: 225
-- Data for Name: sys_dept; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_dept VALUES ('019fa265-8a56-7fce-b72a-344fe2f8ec87', NULL, '总部', 0, NULL, 'active', '2026-07-27 15:06:31.3824+08', '2026-07-27 15:06:31.3824+08');
INSERT INTO sys.sys_dept VALUES ('019fa265-8a60-7d41-9e4e-af23b2a6beab', '019fa265-8a56-7fce-b72a-344fe2f8ec87', '研发部', 0, NULL, 'active', '2026-07-27 15:06:31.391176+08', '2026-07-27 15:06:31.391176+08');
INSERT INTO sys.sys_dept VALUES ('019fa265-8a66-7b6e-a330-46a028be8e37', '019fa265-8a56-7fce-b72a-344fe2f8ec87', '市场部', 0, NULL, 'active', '2026-07-27 15:06:31.397823+08', '2026-07-27 15:06:31.397823+08');


--
-- TOC entry 5156 (class 0 OID 24883)
-- Dependencies: 223
-- Data for Name: sys_dict_data; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_dict_data (id,dict_type,"label",value,sort_order,is_default,status,remark,created_at,updated_at) VALUES
	 ('019fa7b2-986d-7df1-a85a-5b17bb62acc7'::uuid,'visibility_type','私有','private',0,true,'active',NULL,'2026-07-28 15:48:47.339','2026-07-28 15:48:51.075'),
	 ('019fa7b2-cfe7-7016-96ee-4d574ec8ece2'::uuid,'visibility_type','部门','department',1,false,'active',NULL,'2026-07-28 15:49:01.541','2026-07-28 15:49:11.114'),
	 ('019fa7b3-29b6-7248-a609-6bd4eec82fc0'::uuid,'visibility_type','公开','public',2,false,'active',NULL,'2026-07-28 15:49:24.532','2026-07-28 15:49:24.532'),
	 ('019fa7b4-0cf5-7eee-ba8b-7cdfef75cc4d'::uuid,'status','激活','active',0,true,'active',NULL,'2026-07-28 15:50:22.708','2026-07-28 15:50:22.708'),
	 ('019fa7b4-5605-7687-912f-b7a7041fb142'::uuid,'status','已归档','archived',1,false,'active',NULL,'2026-07-28 15:50:41.411','2026-07-28 15:50:41.411'),
	 ('019fa7b4-872c-71c5-b978-39e39c3b15a6'::uuid,'status','已删除','deleted',2,false,'active',NULL,'2026-07-28 15:50:53.994','2026-07-28 15:50:53.994'),
	 ('019fac76-1e71-7d2e-8213-9f30a6681641'::uuid,'reasoning_effort','最低限度','minimal',1,false,'active',NULL,'2026-07-29 14:00:50.031','2026-07-29 14:44:18.929'),
	 ('019fac76-5be6-7d29-b6ed-b597e457be7f'::uuid,'reasoning_effort','中','medium',2,false,'active',NULL,'2026-07-29 14:01:05.764','2026-07-29 14:44:23.170'),
	 ('019fac76-40e6-7aba-841c-abcba09e86e1'::uuid,'reasoning_effort','低','low',3,false,'active',NULL,'2026-07-29 14:00:58.853','2026-07-29 14:44:31.659'),
	 ('019fac76-7b3c-7684-b4ab-2ab06ac2c335'::uuid,'reasoning_effort','高','high',4,false,'active',NULL,'2026-07-29 14:01:13.787','2026-07-29 14:44:34.258');
INSERT INTO sys.sys_dict_data (id,dict_type,"label",value,sort_order,is_default,status,remark,created_at,updated_at) VALUES
	 ('019fac9d-bc25-7f17-a1a7-116b35588dfa'::uuid,'reasoning_effort','关闭','off',0,true,'active',NULL,'2026-07-29 14:44:06.306','2026-07-29 15:12:23.958'),
	 ('019fb76a-ecd2-7ee8-8b7f-4e392fa78bf7'::uuid,'context_window','200K','200000',0,true,'active',NULL,'2026-07-31 17:04:25.807','2026-07-31 17:21:50.178'),
	 ('019fb76b-3440-7e43-a53d-72e96cc30b19'::uuid,'context_window','400K','400000',0,false,'active',NULL,'2026-07-31 17:04:44.095','2026-07-31 17:21:50.178'),
	 ('019fb76b-6c89-7fa2-aa1a-d42e7304d76d'::uuid,'context_window','1M','1000000',0,false,'active',NULL,'2026-07-31 17:04:58.504','2026-07-31 17:21:50.178'),
	 ('019fd72f-efe4-75c4-a936-f14fc1afd2e1'::uuid,'embedding_provider','cohere','cohere',0,true,'active',NULL,'2026-08-06 21:07:50.861','2026-08-06 21:07:50.861'),
	 ('019fd730-0e80-7986-9491-e6aafe481daa'::uuid,'embedding_provider','openai','openai',1,false,'active',NULL,'2026-08-06 21:07:58.642','2026-08-06 21:07:58.642'),
	 ('019fd730-32a1-75c8-9aff-27b5905a0bc4'::uuid,'embedding_provider','dashscope','dashscope',2,false,'active',NULL,'2026-08-06 21:08:07.961','2026-08-06 21:08:07.961'),
	 ('019fd758-16cb-7158-aab8-c0782ce7aecd'::uuid,'sse_event','sources','sources',0,false,'active','引用','2026-08-06 21:51:42.262','2026-08-06 21:51:42.262'),
	 ('019fd758-3ca7-78d2-bbb1-0b13e5520393'::uuid,'sse_event','done','done',0,false,'active','结束','2026-08-06 21:51:51.888','2026-08-06 21:51:51.888'),
	 ('019fd757-dd27-7653-819f-19c03bfed40a'::uuid,'sse_event','answer','answer',0,false,'active','回复','2026-08-06 21:51:27.516','2026-08-06 21:51:58.637');
INSERT INTO sys.sys_dict_data (id,dict_type,"label",value,sort_order,is_default,status,remark,created_at,updated_at) VALUES
	 ('019fd757-b506-7f8f-8787-826083ec4b8d'::uuid,'sse_event','think','think',0,false,'active','思考内容','2026-08-06 21:51:17.071','2026-08-06 21:52:24.121'),
	 ('019fd758-df5f-7fc8-ad10-66385ad25ff3'::uuid,'sse_event','error','error',0,false,'active','错误','2026-08-06 21:52:33.565','2026-08-06 21:52:33.565'),
	 ('019fd75a-69ca-7385-b0a8-049f8c538112'::uuid,'sse_event','feed','feed',0,false,'active','追问','2026-08-06 21:54:14.532','2026-08-06 21:54:14.532');

--
-- TOC entry 5155 (class 0 OID 24864)
-- Dependencies: 222
-- Data for Name: sys_dict_type; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_dict_type (id,"name","type",status,remark,created_at,updated_at) VALUES
	 ('019fa7b2-6490-7587-982f-6b4d9d4f5c21'::uuid,'可见性','visibility_type','active',NULL,'2026-07-28 15:48:34.061','2026-07-28 15:48:34.061'),
	 ('019fa7b3-9a9c-7ed3-aabb-434e923e09c9'::uuid,'进度状态','status','active',NULL,'2026-07-28 15:49:53.435','2026-07-28 15:49:53.435'),
	 ('019fac75-7289-711f-a290-7ca04cfedfb5'::uuid,'推理等级','reasoning_effort','active',NULL,'2026-07-29 14:00:06.022','2026-07-29 14:00:06.022'),
	 ('019fb769-bd93-707d-8246-edec3110ab27'::uuid,'模型上下文窗口','context_window','active',NULL,'2026-07-31 17:03:08.176','2026-07-31 17:21:50.180'),
	 ('019fd72f-7363-7768-8fc9-79e7d2bb291b'::uuid,'嵌入模型协议','embedding_provider','active',NULL,'2026-08-06 21:07:18.399','2026-08-06 21:07:18.399'),
	 ('019fd757-6342-7eee-b1f9-2faf833db3d8'::uuid,'SSE事件','sse_event','active',NULL,'2026-08-06 21:50:56.284','2026-08-06 21:50:56.284');

--
-- TOC entry 5161 (class 0 OID 24985)
-- Dependencies: 228
-- Data for Name: sys_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_menu (id,parent_id,menu_type,"name","path",component,"label",icon,perms,visible,sort_order,status,created_at,updated_at) VALUES
	 ('01900000-0000-7000-8000-000000000002'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-user','/system/user','system-user','用户管理','user',NULL,true,1,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000003'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-role','/system/role','system-role','角色管理','role',NULL,true,2,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000004'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-dept','/system/dept','system-dept','部门管理','dept',NULL,true,3,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000005'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-menu','/system/menu','system-menu','菜单管理','menu',NULL,true,4,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000006'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-dict','/system/dict','system-dict','字典管理','dict',NULL,true,5,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000007'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','system-config','/system/config','system-config','参数管理','config',NULL,true,6,'active','2026-07-27 13:30:44.428','2026-07-27 13:30:44.428'),
	 ('01900000-0000-7000-8000-000000000001'::uuid,NULL,'dir','system','/system',NULL,'系统管理','settings',NULL,true,0,'active','2026-07-27 13:30:44.428','2026-07-27 15:55:59.920'),
	 ('019fa2bd-1633-7227-9b62-33848c740ca0'::uuid,NULL,'dir',NULL,'/agents',NULL,'智能体','智能优化',NULL,true,1,'active','2026-07-27 16:42:08.818','2026-07-27 17:17:05.654'),
	 ('019fa292-b518-785e-9422-262b2239df5b'::uuid,NULL,'dir',NULL,'/rag',NULL,'RAG系统','touzijihuaguanli',NULL,true,2,'active','2026-07-27 15:55:51.447','2026-07-27 17:17:16.234'),
	 ('019fa2bc-83fe-7016-a522-505abbdaf2f4'::uuid,NULL,'dir',NULL,'/script',NULL,'剧本生成','rizhiguanli',NULL,true,4,'active','2026-07-27 16:41:31.389','2026-07-27 17:17:25.528');
INSERT INTO sys.sys_menu (id,parent_id,menu_type,"name","path",component,"label",icon,perms,visible,sort_order,status,created_at,updated_at) VALUES
	 ('019fa2c4-50f2-7b8a-b703-94abbe1b4f31'::uuid,NULL,'dir',NULL,'/draw-design',NULL,'绘制设计','bangongyongpinguanli',NULL,true,3,'active','2026-07-27 16:50:02.610','2026-07-30 15:36:20.128'),
	 ('01900000-0000-7000-8000-000000000008'::uuid,'019fa2c4-50f2-7b8a-b703-94abbe1b4f31'::uuid,'menu','draw','/draw-design/draw','draw','AI 绘图','workflow',NULL,true,30,'active','2026-07-30 15:28:53.757','2026-07-30 16:13:47.702'),
	 ('019fb5b4-95df-77b1-b163-3ab3d460d9e6'::uuid,'01900000-0000-7000-8000-000000000001'::uuid,'menu','model-cfg','/system/model-cfg','system-model','模型管理','Cpu',NULL,true,0,'active','2026-07-31 09:05:38.778','2026-07-31 10:22:43.617'),
	 ('019fa2b2-144f-7b3d-9764-178f22b49ae5'::uuid,'019fa292-b518-785e-9422-262b2239df5b'::uuid,'menu','knowledge-base','/rag/knowledgebase/index','KnowledgeBase','AI知识库管理','Management',NULL,true,0,'active','2026-07-27 16:30:07.436','2026-08-06 20:52:10.095'),
	 ('019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56'::uuid,'019fa292-b518-785e-9422-262b2239df5b'::uuid,'menu','document','/rag/document/index','document','文档管理','List',NULL,true,1,'active','2026-07-27 16:31:34.972','2026-08-06 20:52:16.721');


--
-- TOC entry 5164 (class 0 OID 41516)
-- Dependencies: 244
-- Data for Name: sys_model_config; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_model_config VALUES ('019fb5e7-d9ce-76ec-ac2e-34c3c8a588b7', 'chat', '对话模型', 'deepseek-v4-flash', 'https://api.deepseek.com', '', NULL, 60, 2, 200000, NULL, true, NULL, '2026-07-31 10:01:38.510209+08', '2026-07-31 10:07:52.278889+08');
INSERT INTO sys.sys_model_config VALUES ('019fb5e7-d9ce-7c89-9d32-f87aa2af9749', 'rerank', '重排序模型', 'Qwen3-Embedding-4B', 'http://127.0.0.1:9527', '95279527', 'cohere', NULL, NULL, 200000, NULL, true, NULL, '2026-07-31 10:01:38.510209+08', '2026-07-31 10:08:17.41671+08');
INSERT INTO sys.sys_model_config VALUES ('019fb5e7-d9ce-7c78-8917-1e8e5dac84dc', 'visual', '多模态模型', 'step-3.7-flash', 'https://api.stepfun.com/step_plan/v1', '', NULL, 60, 2, 200000, NULL, true, NULL, '2026-07-31 10:01:38.510209+08', '2026-07-31 10:08:56.0961+08');
INSERT INTO sys.sys_model_config VALUES ('019fb5e7-d9ce-7c24-8853-c06e3c973c8e', 'rewrite', '改写压缩模型', 'Qwen3.5-2B', 'http://127.0.0.1:9528/v1', '95279527', NULL, NULL, NULL, 200000, NULL, true, NULL, '2026-07-31 10:01:38.510209+08', '2026-07-31 10:39:04.185031+08');


--
-- TOC entry 5160 (class 0 OID 24962)
-- Dependencies: 227
-- Data for Name: sys_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_role VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '研究员', 'researcher', 'all', 0, 'active', NULL, '2026-07-27 14:12:03.105254+08', '2026-07-27 14:12:03.105254+08');
INSERT INTO sys.sys_role VALUES ('019fa23b-f8b7-7bd3-814d-81334345475f', '助理研究员', 'Assistant-Researcher', 'all', 0, 'active', NULL, '2026-07-27 14:21:07.123234+08', '2026-07-27 14:21:07.123234+08');
INSERT INTO sys.sys_role VALUES ('019fa23c-7523-7770-ab1e-4b56dec4ba07', '研究实习员', 'Research-Intern', 'all', 0, 'active', NULL, '2026-07-27 14:21:38.97855+08', '2026-07-27 14:21:38.97855+08');
INSERT INTO sys.sys_role VALUES ('019fa2ee-842e-794b-bf3b-76fe95c78a83', '管理员', 'admin', 'all', 0, 'active', NULL, '2026-07-27 17:36:08.236382+08', '2026-07-27 17:36:08.236382+08');


--
-- TOC entry 5163 (class 0 OID 25015)
-- Dependencies: 230
-- Data for Name: sys_role_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000001');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000002');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000003');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000004');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000005');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000006');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '01900000-0000-7000-8000-000000000007');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2bd-1633-7227-9b62-33848c740ca0');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa292-b518-785e-9422-262b2239df5b');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2b2-144f-7b3d-9764-178f22b49ae5');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2bc-83fe-7016-a522-505abbdaf2f4');
INSERT INTO sys.sys_role_menu VALUES ('019fa233-aba6-7e4b-b950-8beb9ae652bf', '019fa2c4-50f2-7b8a-b703-94abbe1b4f31');


--
-- TOC entry 5159 (class 0 OID 24942)
-- Dependencies: 226
-- Data for Name: sys_user; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_user VALUES ('01900000-0000-7000-8000-0000000000a1', 'admin', '$2b$12$ZDbTEc7fpaM5878wuIBBEeqj0T32LYtLnsCPWRggRtorRlzRdQiuu', '管理员', NULL, NULL, NULL, NULL, 'active', NULL, '2026-07-27 13:49:02.394632+08', '2026-07-27 13:49:02.394632+08');
INSERT INTO sys.sys_user VALUES ('019fa265-8bb9-7872-97d1-47b9c52897b0', 'yx01', '$2b$12$6GNOCSpacPSyPYVrtL7Hy.rAsYoU4ffgZleheOAHbFVUT/Nkm2joK', '市场一号', '019fa265-8a66-7b6e-a330-46a028be8e37', NULL, NULL, NULL, 'active', NULL, '2026-07-27 15:06:31.573371+08', '2026-07-27 15:54:04.965226+08');
INSERT INTO sys.sys_user VALUES ('019fa265-8b0e-7d2e-90a0-2c6a114bd327', 'yg01', '$2b$12$llx6T92WUUBP6wzuJuqwZebqNJw72LDlM.T2VqUXpdmMis1O.6zEi', '研发一号', '019fa265-8a60-7d41-9e4e-af23b2a6beab', NULL, NULL, NULL, 'active', NULL, '2026-07-27 15:06:31.403725+08', '2026-07-27 15:54:13.483248+08');


--
-- TOC entry 5162 (class 0 OID 25007)
-- Dependencies: 229
-- Data for Name: sys_user_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

INSERT INTO sys.sys_user_role VALUES ('019fa265-8b0e-7d2e-90a0-2c6a114bd327', '019fa23b-f8b7-7bd3-814d-81334345475f');
INSERT INTO sys.sys_user_role VALUES ('019fa265-8bb9-7872-97d1-47b9c52897b0', '019fa23c-7523-7770-ab1e-4b56dec4ba07');
INSERT INTO sys.sys_user_role VALUES ('01900000-0000-7000-8000-0000000000a1', '019fa2ee-842e-794b-bf3b-76fe95c78a83');


