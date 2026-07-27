--
-- PostgreSQL database dump
--

\restrict yIS9sbSaObLhsGufcsx3VfChAPOJ3H3QYfVu0lvhD4fh8LKSK0q8TyT9GiuZ9cj

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

-- Started on 2026-07-27 18:58:59

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

DROP DATABASE multi_agent_db;
--
-- TOC entry 5190 (class 1262 OID 16388)
-- Name: multi_agent_db; Type: DATABASE; Schema: -; Owner: postgres
--

CREATE DATABASE multi_agent_db WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'Chinese (Simplified)_China.936';


ALTER DATABASE multi_agent_db OWNER TO postgres;

\unrestrict yIS9sbSaObLhsGufcsx3VfChAPOJ3H3QYfVu0lvhD4fh8LKSK0q8TyT9GiuZ9cj
\connect multi_agent_db
\restrict yIS9sbSaObLhsGufcsx3VfChAPOJ3H3QYfVu0lvhD4fh8LKSK0q8TyT9GiuZ9cj

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 6 (class 2615 OID 16389)
-- Name: rag; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA rag;


ALTER SCHEMA rag OWNER TO postgres;

--
-- TOC entry 7 (class 2615 OID 24679)
-- Name: sys; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA sys;


ALTER SCHEMA sys OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 233 (class 1259 OID 25103)
-- Name: rag_chunks; Type: TABLE; Schema: rag; Owner: postgres
--

CREATE TABLE rag.rag_chunks (
    id uuid DEFAULT uuidv7() NOT NULL,
    dept_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    document_id uuid NOT NULL,
    parent_chunk_id uuid,
    document_version integer NOT NULL,
    level smallint DEFAULT 0 NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    token_count integer,
    char_start integer,
    char_end integer,
    chapter_title text,
    page_start integer,
    page_end integer,
    content_hash character(64),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE rag.rag_chunks OWNER TO postgres;

--
-- TOC entry 232 (class 1259 OID 25072)
-- Name: rag_documents; Type: TABLE; Schema: rag; Owner: postgres
--

CREATE TABLE rag.rag_documents (
    id uuid DEFAULT uuidv7() NOT NULL,
    dept_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    knowledge_base_id uuid NOT NULL,
    folder_id uuid,
    source_uri text,
    source_system character varying(50),
    title text,
    doc_type character varying(50),
    content text,
    content_hash character(64),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_updated_at timestamp with time zone,
    valid_from timestamp with time zone DEFAULT now() NOT NULL,
    valid_until timestamp with time zone,
    last_verified_at timestamp with time zone,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE rag.rag_documents OWNER TO postgres;

--
-- TOC entry 230 (class 1259 OID 25023)
-- Name: rag_folders; Type: TABLE; Schema: rag; Owner: postgres
--

CREATE TABLE rag.rag_folders (
    id uuid DEFAULT uuidv7() NOT NULL,
    dept_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    knowledge_base_id uuid NOT NULL,
    parent_id uuid,
    name text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE rag.rag_folders OWNER TO postgres;

--
-- TOC entry 231 (class 1259 OID 25045)
-- Name: rag_knowledge_bases; Type: TABLE; Schema: rag; Owner: postgres
--

CREATE TABLE rag.rag_knowledge_bases (
    id uuid DEFAULT uuidv7() NOT NULL,
    dept_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    name text NOT NULL,
    description text,
    icon character varying(100),
    qdrant_collection character varying(200) NOT NULL,
    embedding_provider character varying(50),
    embedding_model character varying(100),
    embedding_dim integer,
    visibility character varying(20) DEFAULT 'private'::character varying NOT NULL,
    owner character varying(100),
    document_count integer DEFAULT 0 NOT NULL,
    total_chunk_count integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE rag.rag_knowledge_bases OWNER TO postgres;

--
-- TOC entry 223 (class 1259 OID 24906)
-- Name: sys_config; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_config (
    id uuid DEFAULT uuidv7() NOT NULL,
    name character varying(100) NOT NULL,
    key character varying(100) NOT NULL,
    value text,
    is_builtin boolean DEFAULT false NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_config OWNER TO postgres;

--
-- TOC entry 224 (class 1259 OID 24925)
-- Name: sys_dept; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_dept (
    id uuid DEFAULT uuidv7() NOT NULL,
    parent_id uuid,
    name character varying(100) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    leader character varying(100),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_dept OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 24883)
-- Name: sys_dict_data; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_dict_data (
    id uuid DEFAULT uuidv7() NOT NULL,
    dict_type character varying(100) NOT NULL,
    label character varying(100) NOT NULL,
    value character varying(100) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_dict_data OWNER TO postgres;

--
-- TOC entry 221 (class 1259 OID 24864)
-- Name: sys_dict_type; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_dict_type (
    id uuid DEFAULT uuidv7() NOT NULL,
    name character varying(100) NOT NULL,
    type character varying(100) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_dict_type OWNER TO postgres;

--
-- TOC entry 227 (class 1259 OID 24985)
-- Name: sys_menu; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_menu (
    id uuid DEFAULT uuidv7() NOT NULL,
    parent_id uuid,
    menu_type character varying(20) NOT NULL,
    name character varying(100),
    path character varying(200),
    component character varying(100),
    label character varying(100) NOT NULL,
    icon character varying(100),
    perms character varying(100),
    visible boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_menu OWNER TO postgres;

--
-- TOC entry 226 (class 1259 OID 24962)
-- Name: sys_role; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_role (
    id uuid DEFAULT uuidv7() NOT NULL,
    name character varying(100) NOT NULL,
    role_key character varying(100) NOT NULL,
    data_scope character varying(20) DEFAULT 'all'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_role OWNER TO postgres;

--
-- TOC entry 229 (class 1259 OID 25015)
-- Name: sys_role_menu; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_role_menu (
    role_id uuid NOT NULL,
    menu_id uuid NOT NULL
);


ALTER TABLE sys.sys_role_menu OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 24942)
-- Name: sys_user; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_user (
    id uuid DEFAULT uuidv7() NOT NULL,
    username character varying(64) NOT NULL,
    password character varying(100) NOT NULL,
    nickname character varying(100),
    dept_id uuid,
    email character varying(100),
    phone character varying(20),
    avatar character varying(200),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE sys.sys_user OWNER TO postgres;

--
-- TOC entry 228 (class 1259 OID 25007)
-- Name: sys_user_role; Type: TABLE; Schema: sys; Owner: postgres
--

CREATE TABLE sys.sys_user_role (
    user_id uuid NOT NULL,
    role_id uuid NOT NULL
);


ALTER TABLE sys.sys_user_role OWNER TO postgres;

--
-- TOC entry 5184 (class 0 OID 25103)
-- Dependencies: 233
-- Data for Name: rag_chunks; Type: TABLE DATA; Schema: rag; Owner: postgres
--

COPY rag.rag_chunks (id, dept_id, document_id, parent_chunk_id, document_version, level, chunk_index, content, token_count, char_start, char_end, chapter_title, page_start, page_end, content_hash, metadata, created_at) FROM stdin;
\.


--
-- TOC entry 5183 (class 0 OID 25072)
-- Dependencies: 232
-- Data for Name: rag_documents; Type: TABLE DATA; Schema: rag; Owner: postgres
--

COPY rag.rag_documents (id, dept_id, knowledge_base_id, folder_id, source_uri, source_system, title, doc_type, content, content_hash, metadata, source_updated_at, valid_from, valid_until, last_verified_at, status, version, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 5181 (class 0 OID 25023)
-- Dependencies: 230
-- Data for Name: rag_folders; Type: TABLE DATA; Schema: rag; Owner: postgres
--

COPY rag.rag_folders (id, dept_id, knowledge_base_id, parent_id, name, sort_order, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 5182 (class 0 OID 25045)
-- Dependencies: 231
-- Data for Name: rag_knowledge_bases; Type: TABLE DATA; Schema: rag; Owner: postgres
--

COPY rag.rag_knowledge_bases (id, dept_id, name, description, icon, qdrant_collection, embedding_provider, embedding_model, embedding_dim, visibility, owner, document_count, total_chunk_count, status, created_at, updated_at) FROM stdin;
019fa318-76ad-77e3-aa51-d5ba5c7b528f	019fa31874a473fbbbfa1968e318020d	冒烟B部门知识库	\N	\N	kb_019fa31876ad77e3aa51d5ba5c7b528f_v1	\N	\N	\N	private	smoke_jerry	0	0	deleted	2026-07-27 18:21:57.294487+08	2026-07-27 18:21:57.478277+08
\.


--
-- TOC entry 5174 (class 0 OID 24906)
-- Dependencies: 223
-- Data for Name: sys_config; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_config (id, name, key, value, is_builtin, remark, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 5175 (class 0 OID 24925)
-- Dependencies: 224
-- Data for Name: sys_dept; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_dept (id, parent_id, name, sort_order, leader, status, created_at, updated_at) FROM stdin;
019fa265-8a56-7fce-b72a-344fe2f8ec87	\N	总部	0	\N	active	2026-07-27 15:06:31.3824+08	2026-07-27 15:06:31.3824+08
019fa265-8a60-7d41-9e4e-af23b2a6beab	019fa265-8a56-7fce-b72a-344fe2f8ec87	研发部	0	\N	active	2026-07-27 15:06:31.391176+08	2026-07-27 15:06:31.391176+08
019fa265-8a66-7b6e-a330-46a028be8e37	019fa265-8a56-7fce-b72a-344fe2f8ec87	市场部	0	\N	active	2026-07-27 15:06:31.397823+08	2026-07-27 15:06:31.397823+08
\.


--
-- TOC entry 5173 (class 0 OID 24883)
-- Dependencies: 222
-- Data for Name: sys_dict_data; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_dict_data (id, dict_type, label, value, sort_order, is_default, status, remark, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 5172 (class 0 OID 24864)
-- Dependencies: 221
-- Data for Name: sys_dict_type; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_dict_type (id, name, type, status, remark, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 5178 (class 0 OID 24985)
-- Dependencies: 227
-- Data for Name: sys_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_menu (id, parent_id, menu_type, name, path, component, label, icon, perms, visible, sort_order, status, created_at, updated_at) FROM stdin;
01900000-0000-7000-8000-000000000002	01900000-0000-7000-8000-000000000001	menu	system-user	/system/user	system-user	用户管理	user	\N	t	1	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000003	01900000-0000-7000-8000-000000000001	menu	system-role	/system/role	system-role	角色管理	role	\N	t	2	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000004	01900000-0000-7000-8000-000000000001	menu	system-dept	/system/dept	system-dept	部门管理	dept	\N	t	3	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000005	01900000-0000-7000-8000-000000000001	menu	system-menu	/system/menu	system-menu	菜单管理	menu	\N	t	4	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000006	01900000-0000-7000-8000-000000000001	menu	system-dict	/system/dict	system-dict	字典管理	dict	\N	t	5	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000007	01900000-0000-7000-8000-000000000001	menu	system-config	/system/config	system-config	参数管理	config	\N	t	6	active	2026-07-27 13:30:44.428008+08	2026-07-27 13:30:44.428008+08
01900000-0000-7000-8000-000000000001	\N	dir	system	/system	\N	系统管理	settings	\N	t	0	active	2026-07-27 13:30:44.428008+08	2026-07-27 15:55:59.920293+08
019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56	019fa292-b518-785e-9422-262b2239df5b	menu	document	/rag/document	document	文档管理	List	\N	t	1	active	2026-07-27 16:31:34.972524+08	2026-07-27 16:31:34.972524+08
019fa2b2-144f-7b3d-9764-178f22b49ae5	019fa292-b518-785e-9422-262b2239df5b	menu	knowledge-base	/rag/KnowledgeBase	KnowledgeBase	AI知识库管理	Management	\N	t	0	active	2026-07-27 16:30:07.436885+08	2026-07-27 16:31:56.427309+08
019fa2c4-50f2-7b8a-b703-94abbe1b4f31	\N	dir	\N	/redraw	\N	图像重绘	bangongyongpinguanli	\N	t	3	active	2026-07-27 16:50:02.610325+08	2026-07-27 16:50:02.610325+08
019fa2bd-1633-7227-9b62-33848c740ca0	\N	dir	\N	/agents	\N	智能体	智能优化	\N	t	1	active	2026-07-27 16:42:08.818006+08	2026-07-27 17:17:05.654201+08
019fa292-b518-785e-9422-262b2239df5b	\N	dir	\N	/rag	\N	RAG系统	touzijihuaguanli	\N	t	2	active	2026-07-27 15:55:51.447521+08	2026-07-27 17:17:16.234366+08
019fa2bc-83fe-7016-a522-505abbdaf2f4	\N	dir	\N	/script	\N	剧本生成	rizhiguanli	\N	t	4	active	2026-07-27 16:41:31.389499+08	2026-07-27 17:17:25.528507+08
\.


--
-- TOC entry 5177 (class 0 OID 24962)
-- Dependencies: 226
-- Data for Name: sys_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_role (id, name, role_key, data_scope, sort_order, status, remark, created_at, updated_at) FROM stdin;
019fa233-aba6-7e4b-b950-8beb9ae652bf	研究员	researcher	all	0	active	\N	2026-07-27 14:12:03.105254+08	2026-07-27 14:12:03.105254+08
019fa23b-f8b7-7bd3-814d-81334345475f	助理研究员	Assistant-Researcher	all	0	active	\N	2026-07-27 14:21:07.123234+08	2026-07-27 14:21:07.123234+08
019fa23c-7523-7770-ab1e-4b56dec4ba07	研究实习员	Research-Intern	all	0	active	\N	2026-07-27 14:21:38.97855+08	2026-07-27 14:21:38.97855+08
019fa2ee-842e-794b-bf3b-76fe95c78a83	管理员	admin	all	0	active	\N	2026-07-27 17:36:08.236382+08	2026-07-27 17:36:08.236382+08
\.


--
-- TOC entry 5180 (class 0 OID 25015)
-- Dependencies: 229
-- Data for Name: sys_role_menu; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_role_menu (role_id, menu_id) FROM stdin;
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000001
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000002
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000003
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000004
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000005
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000006
019fa233-aba6-7e4b-b950-8beb9ae652bf	01900000-0000-7000-8000-000000000007
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa2bd-1633-7227-9b62-33848c740ca0
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa292-b518-785e-9422-262b2239df5b
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa2b2-144f-7b3d-9764-178f22b49ae5
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa2b3-6a3f-73f0-bc5a-7adb54c3cf56
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa2bc-83fe-7016-a522-505abbdaf2f4
019fa233-aba6-7e4b-b950-8beb9ae652bf	019fa2c4-50f2-7b8a-b703-94abbe1b4f31
\.


--
-- TOC entry 5176 (class 0 OID 24942)
-- Dependencies: 225
-- Data for Name: sys_user; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_user (id, username, password, nickname, dept_id, email, phone, avatar, status, remark, created_at, updated_at) FROM stdin;
01900000-0000-7000-8000-0000000000a1	admin	$2b$12$ZDbTEc7fpaM5878wuIBBEeqj0T32LYtLnsCPWRggRtorRlzRdQiuu	管理员	\N	\N	\N	\N	active	\N	2026-07-27 13:49:02.394632+08	2026-07-27 13:49:02.394632+08
019fa265-8bb9-7872-97d1-47b9c52897b0	yx01	$2b$12$6GNOCSpacPSyPYVrtL7Hy.rAsYoU4ffgZleheOAHbFVUT/Nkm2joK	市场一号	019fa265-8a66-7b6e-a330-46a028be8e37	\N	\N	\N	active	\N	2026-07-27 15:06:31.573371+08	2026-07-27 15:54:04.965226+08
019fa265-8b0e-7d2e-90a0-2c6a114bd327	yg01	$2b$12$llx6T92WUUBP6wzuJuqwZebqNJw72LDlM.T2VqUXpdmMis1O.6zEi	研发一号	019fa265-8a60-7d41-9e4e-af23b2a6beab	\N	\N	\N	active	\N	2026-07-27 15:06:31.403725+08	2026-07-27 15:54:13.483248+08
\.


--
-- TOC entry 5179 (class 0 OID 25007)
-- Dependencies: 228
-- Data for Name: sys_user_role; Type: TABLE DATA; Schema: sys; Owner: postgres
--

COPY sys.sys_user_role (user_id, role_id) FROM stdin;
019fa265-8b0e-7d2e-90a0-2c6a114bd327	019fa23b-f8b7-7bd3-814d-81334345475f
019fa265-8bb9-7872-97d1-47b9c52897b0	019fa23c-7523-7770-ab1e-4b56dec4ba07
01900000-0000-7000-8000-0000000000a1	019fa2ee-842e-794b-bf3b-76fe95c78a83
\.


--
-- TOC entry 5022 (class 2606 OID 25125)
-- Name: rag_chunks rag_chunks_document_id_document_version_level_chunk_index_key; Type: CONSTRAINT; Schema: rag; Owner: postgres
--

ALTER TABLE ONLY rag.rag_chunks
    ADD CONSTRAINT rag_chunks_document_id_document_version_level_chunk_index_key UNIQUE (document_id, document_version, level, chunk_index);


--
-- TOC entry 5024 (class 2606 OID 25123)
-- Name: rag_chunks rag_chunks_pkey; Type: CONSTRAINT; Schema: rag; Owner: postgres
--

ALTER TABLE ONLY rag.rag_chunks
    ADD CONSTRAINT rag_chunks_pkey PRIMARY KEY (id);


--
-- TOC entry 5015 (class 2606 OID 25095)
-- Name: rag_documents rag_documents_pkey; Type: CONSTRAINT; Schema: rag; Owner: postgres
--

ALTER TABLE ONLY rag.rag_documents
    ADD CONSTRAINT rag_documents_pkey PRIMARY KEY (id);


--
-- TOC entry 5002 (class 2606 OID 25041)
-- Name: rag_folders rag_folders_pkey; Type: CONSTRAINT; Schema: rag; Owner: postgres
--

ALTER TABLE ONLY rag.rag_folders
    ADD CONSTRAINT rag_folders_pkey PRIMARY KEY (id);


--
-- TOC entry 5006 (class 2606 OID 25069)
-- Name: rag_knowledge_bases rag_knowledge_bases_pkey; Type: CONSTRAINT; Schema: rag; Owner: postgres
--

ALTER TABLE ONLY rag.rag_knowledge_bases
    ADD CONSTRAINT rag_knowledge_bases_pkey PRIMARY KEY (id);


--
-- TOC entry 4974 (class 2606 OID 24924)
-- Name: sys_config sys_config_key_key; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_config
    ADD CONSTRAINT sys_config_key_key UNIQUE (key);


--
-- TOC entry 4976 (class 2606 OID 24922)
-- Name: sys_config sys_config_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_config
    ADD CONSTRAINT sys_config_pkey PRIMARY KEY (id);


--
-- TOC entry 4979 (class 2606 OID 24940)
-- Name: sys_dept sys_dept_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_dept
    ADD CONSTRAINT sys_dept_pkey PRIMARY KEY (id);


--
-- TOC entry 4972 (class 2606 OID 24904)
-- Name: sys_dict_data sys_dict_data_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_dict_data
    ADD CONSTRAINT sys_dict_data_pkey PRIMARY KEY (id);


--
-- TOC entry 4967 (class 2606 OID 24880)
-- Name: sys_dict_type sys_dict_type_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_dict_type
    ADD CONSTRAINT sys_dict_type_pkey PRIMARY KEY (id);


--
-- TOC entry 4969 (class 2606 OID 24882)
-- Name: sys_dict_type sys_dict_type_type_key; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_dict_type
    ADD CONSTRAINT sys_dict_type_type_key UNIQUE (type);


--
-- TOC entry 4991 (class 2606 OID 25005)
-- Name: sys_menu sys_menu_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_menu
    ADD CONSTRAINT sys_menu_pkey PRIMARY KEY (id);


--
-- TOC entry 4997 (class 2606 OID 25021)
-- Name: sys_role_menu sys_role_menu_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_role_menu
    ADD CONSTRAINT sys_role_menu_pkey PRIMARY KEY (role_id, menu_id);


--
-- TOC entry 4986 (class 2606 OID 24982)
-- Name: sys_role sys_role_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_role
    ADD CONSTRAINT sys_role_pkey PRIMARY KEY (id);


--
-- TOC entry 4988 (class 2606 OID 24984)
-- Name: sys_role sys_role_role_key_key; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_role
    ADD CONSTRAINT sys_role_role_key_key UNIQUE (role_key);


--
-- TOC entry 4982 (class 2606 OID 24958)
-- Name: sys_user sys_user_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_user
    ADD CONSTRAINT sys_user_pkey PRIMARY KEY (id);


--
-- TOC entry 4994 (class 2606 OID 25013)
-- Name: sys_user_role sys_user_role_pkey; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_user_role
    ADD CONSTRAINT sys_user_role_pkey PRIMARY KEY (user_id, role_id);


--
-- TOC entry 4984 (class 2606 OID 24960)
-- Name: sys_user sys_user_username_key; Type: CONSTRAINT; Schema: sys; Owner: postgres
--

ALTER TABLE ONLY sys.sys_user
    ADD CONSTRAINT sys_user_username_key UNIQUE (username);


--
-- TOC entry 5016 (class 1259 OID 25126)
-- Name: idx_rag_chunks_dept; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_chunks_dept ON rag.rag_chunks USING btree (dept_id);


--
-- TOC entry 5017 (class 1259 OID 25127)
-- Name: idx_rag_chunks_document; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_chunks_document ON rag.rag_chunks USING btree (document_id, document_version);


--
-- TOC entry 5018 (class 1259 OID 25129)
-- Name: idx_rag_chunks_level; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_chunks_level ON rag.rag_chunks USING btree (level);


--
-- TOC entry 5019 (class 1259 OID 25130)
-- Name: idx_rag_chunks_metadata_gin; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_chunks_metadata_gin ON rag.rag_chunks USING gin (metadata);


--
-- TOC entry 5020 (class 1259 OID 25128)
-- Name: idx_rag_chunks_parent; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_chunks_parent ON rag.rag_chunks USING btree (parent_chunk_id);


--
-- TOC entry 5007 (class 1259 OID 25096)
-- Name: idx_rag_documents_dept; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_dept ON rag.rag_documents USING btree (dept_id);


--
-- TOC entry 5008 (class 1259 OID 25098)
-- Name: idx_rag_documents_folder; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_folder ON rag.rag_documents USING btree (folder_id);


--
-- TOC entry 5009 (class 1259 OID 25097)
-- Name: idx_rag_documents_kb; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_kb ON rag.rag_documents USING btree (knowledge_base_id);


--
-- TOC entry 5010 (class 1259 OID 25100)
-- Name: idx_rag_documents_metadata_gin; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_metadata_gin ON rag.rag_documents USING gin (metadata);


--
-- TOC entry 5011 (class 1259 OID 25099)
-- Name: idx_rag_documents_source_hash; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_source_hash ON rag.rag_documents USING btree (source_uri, content_hash);


--
-- TOC entry 5012 (class 1259 OID 25101)
-- Name: idx_rag_documents_status; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_status ON rag.rag_documents USING btree (status) WHERE ((status)::text <> 'deleted'::text);


--
-- TOC entry 5013 (class 1259 OID 25102)
-- Name: idx_rag_documents_valid_until; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_documents_valid_until ON rag.rag_documents USING btree (valid_until) WHERE (valid_until IS NOT NULL);


--
-- TOC entry 4998 (class 1259 OID 25042)
-- Name: idx_rag_folders_dept; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_folders_dept ON rag.rag_folders USING btree (dept_id);


--
-- TOC entry 4999 (class 1259 OID 25043)
-- Name: idx_rag_folders_kb; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_folders_kb ON rag.rag_folders USING btree (knowledge_base_id);


--
-- TOC entry 5000 (class 1259 OID 25044)
-- Name: idx_rag_folders_parent; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_folders_parent ON rag.rag_folders USING btree (parent_id);


--
-- TOC entry 5003 (class 1259 OID 25070)
-- Name: idx_rag_kb_dept; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_kb_dept ON rag.rag_knowledge_bases USING btree (dept_id);


--
-- TOC entry 5004 (class 1259 OID 25071)
-- Name: idx_rag_kb_status; Type: INDEX; Schema: rag; Owner: postgres
--

CREATE INDEX idx_rag_kb_status ON rag.rag_knowledge_bases USING btree (status) WHERE ((status)::text <> 'deleted'::text);


--
-- TOC entry 4977 (class 1259 OID 24941)
-- Name: idx_sys_dept_parent; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_dept_parent ON sys.sys_dept USING btree (parent_id);


--
-- TOC entry 4970 (class 1259 OID 24905)
-- Name: idx_sys_dict_data_type; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_dict_data_type ON sys.sys_dict_data USING btree (dict_type);


--
-- TOC entry 4989 (class 1259 OID 25006)
-- Name: idx_sys_menu_parent; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_menu_parent ON sys.sys_menu USING btree (parent_id);


--
-- TOC entry 4995 (class 1259 OID 25022)
-- Name: idx_sys_role_menu_menu; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_role_menu_menu ON sys.sys_role_menu USING btree (menu_id);


--
-- TOC entry 4980 (class 1259 OID 24961)
-- Name: idx_sys_user_dept; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_user_dept ON sys.sys_user USING btree (dept_id);


--
-- TOC entry 4992 (class 1259 OID 25014)
-- Name: idx_sys_user_role_role; Type: INDEX; Schema: sys; Owner: postgres
--

CREATE INDEX idx_sys_user_role_role ON sys.sys_user_role USING btree (role_id);


-- Completed on 2026-07-27 18:58:59

--
-- PostgreSQL database dump complete
--

\unrestrict yIS9sbSaObLhsGufcsx3VfChAPOJ3H3QYfVu0lvhD4fh8LKSK0q8TyT9GiuZ9cj

