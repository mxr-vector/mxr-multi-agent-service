<script setup lang="ts">
const knowledgeBases = [
    { name: '产品知识中心', description: '产品说明、操作手册与版本记录', documents: 128, updated: '今天 10:24', status: '已启用' },
    { name: '客户支持资料', description: '常见问题、处理规范与服务案例', documents: 76, updated: '昨天 16:40', status: '已启用' },
    { name: '研发技术文档', description: '架构设计、接口约定与排障指南', documents: 214, updated: '2026-07-21', status: '处理中' },
]
</script>

<template>
    <section class="rag-page">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / KNOWLEDGE BASE</p>
                <h1>知识库管理</h1>
                <p>创建并维护为智能体提供检索上下文的知识库。</p>
            </div><button class="primary-button" type="button">＋ 新建知识库</button>
        </header>
        <section class="summary-grid">
            <article><span>知识库总数</span><strong>03</strong><small>全部知识源</small></article>
            <article><span>已收录文档</span><strong>418</strong><small>较上周 +24</small></article>
            <article><span>向量化进度</span><strong>96%</strong><small>12 份文档处理中</small></article>
        </section>
        <section class="content-card">
            <div class="toolbar">
                <div>
                    <h2>知识库列表</h2><span>按最近更新时间排序</span>
                </div><input aria-label="搜索知识库" placeholder="搜索知识库" />
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>知识库</th>
                            <th>文档数量</th>
                            <th>最近更新</th>
                            <th>状态</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="base in knowledgeBases" :key="base.name">
                            <td><strong>{{ base.name }}</strong><span>{{ base.description }}</span></td>
                            <td>{{ base.documents }} 份</td>
                            <td>{{ base.updated }}</td>
                            <td><em :class="{ processing: base.status === '处理中' }">{{ base.status }}</em></td>
                            <td><button class="text-button" type="button">管理</button></td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>

<style scoped>
.rag-page {
    display: grid;
    gap: 24px;
    max-width: 1280px;
    margin: 0 auto;
    color: #273249
}

.page-header,
.toolbar {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 20px
}

.eyebrow {
    margin: 0 0 8px;
    color: #7b89b9;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.15px
}

h1,
h2,
p {
    margin-top: 0
}

h1 {
    margin-bottom: 9px;
    font-size: clamp(26px, 3vw, 34px);
    letter-spacing: -1px
}

.page-header p:not(.eyebrow) {
    margin-bottom: 0;
    color: #788397;
    font-size: 14px
}

.primary-button {
    min-height: 40px;
    padding: 0 16px;
    border: 0;
    border-radius: 9px;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
    font-size: 13px;
    font-weight: 600
}

.summary-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px
}

.summary-grid article,
.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
}

.summary-grid article {
    display: grid;
    gap: 7px;
    padding: 20px
}

.summary-grid span,
.summary-grid small,
.toolbar span,
td span {
    color: #7d879a;
    font-size: 12px
}

.summary-grid strong {
    font-size: 28px;
    letter-spacing: -1px
}

.summary-grid small {
    color: #4eab83
}

.toolbar {
    align-items: center;
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5
}

h2 {
    margin-bottom: 4px;
    font-size: 16px
}

input {
    width: 205px;
    padding: 9px 11px;
    border: 1px solid #dfe4ef;
    border-radius: 8px;
    outline: 0;
    color: #34405a
}

input:focus {
    border-color: #8091e8;
    box-shadow: 0 0 0 3px rgb(128 145 232 / 12%)
}

.table-wrap {
    overflow-x: auto
}

table {
    width: 100%;
    border-collapse: collapse;
    text-align: left
}

th,
td {
    padding: 16px 20px;
    border-bottom: 1px solid #f0f2f6;
    font-size: 13px;
    white-space: nowrap
}

th {
    color: #8993a5;
    font-size: 11px;
    font-weight: 600
}

tbody tr:last-child td {
    border-bottom: 0
}

td:first-child {
    min-width: 270px
}

td strong,
td span {
    display: block
}

td span {
    margin-top: 5px
}

em {
    padding: 4px 8px;
    border-radius: 99px;
    color: #328161;
    background: #eaf7f1;
    font-size: 11px;
    font-style: normal
}

em.processing {
    color: #a86d19;
    background: #fff4df
}

.text-button {
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600
}

@media(max-width:720px) {

    .page-header,
    .toolbar {
        align-items: flex-start;
        flex-direction: column
    }

    .summary-grid {
        grid-template-columns: 1fr
    }

    input {
        width: 100%
    }
}
</style>