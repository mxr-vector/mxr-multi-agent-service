<script setup lang="ts">
const documents = [
    { name: '产品使用手册 V3.2.pdf', base: '产品知识中心', category: '产品文档', size: '4.8 MB', updated: '今天 10:24', status: '已完成' },
    { name: '退款处理流程.md', base: '客户支持资料', category: '服务规范', size: '36 KB', updated: '昨天 16:40', status: '已完成' },
    { name: '检索服务架构设计.docx', base: '研发技术文档', category: '技术方案', size: '1.2 MB', updated: '昨天 14:12', status: '解析中' },
    { name: '新员工培训指南.pdf', base: '客户支持资料', category: '培训资料', size: '2.6 MB', updated: '2026-07-21', status: '待处理' },
]
</script>

<template>
    <section class="document-page">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / DOCUMENTS</p>
                <h1>文档管理</h1>
                <p>将文档导入知识库，并跟踪解析与向量化状态。</p>
            </div><button class="primary-button" type="button">上传文档</button>
        </header>
        <section class="upload-zone"><span class="upload-icon">↑</span>
            <div><strong>拖放文件至此处，或选择本地文件</strong>
                <p>支持 PDF、DOCX、Markdown、TXT，单个文件不超过 50 MB</p>
            </div><button type="button">选择文件</button>
        </section>
        <section class="content-card">
            <div class="toolbar">
                <div>
                    <h2>全部文档</h2><span>共 418 份文档</span>
                </div>
                <div class="filters"><button type="button">全部知识库⌄</button><button type="button">全部状态⌄</button></div>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>文档</th>
                            <th>所属知识库</th>
                            <th>分类</th>
                            <th>大小</th>
                            <th>更新时间</th>
                            <th>状态</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="document in documents" :key="document.name">
                            <td><strong>{{ document.name }}</strong></td>
                            <td>{{ document.base }}</td>
                            <td>{{ document.category }}</td>
                            <td>{{ document.size }}</td>
                            <td>{{ document.updated }}</td>
                            <td><em :class="{ parsing: document.status === '解析中', pending: document.status === '待处理' }">{{
                                    document.status }}</em></td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>

<style scoped>
.document-page {
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

.upload-zone {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 20px 24px;
    border: 1px dashed #b8c4ed;
    border-radius: 13px;
    background: #f9faff
}

.upload-icon {
    display: grid;
    width: 38px;
    height: 38px;
    place-items: center;
    border-radius: 10px;
    color: #526ae2;
    background: #e9edff;
    font-size: 21px
}

.upload-zone strong {
    font-size: 13px
}

.upload-zone p {
    margin: 5px 0 0;
    color: #7d879a;
    font-size: 12px
}

.upload-zone button,
.filters button {
    padding: 8px 11px;
    border: 1px solid #dfe4ef;
    border-radius: 8px;
    color: #59657b;
    background: #fff;
    font-size: 12px
}

.upload-zone button {
    margin-left: auto
}

.content-card {
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
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

.toolbar span {
    color: #7d879a;
    font-size: 12px
}

.filters {
    display: flex;
    gap: 8px
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
    color: #4d5970;
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

td strong {
    color: #364158
}

em {
    padding: 4px 8px;
    border-radius: 99px;
    color: #328161;
    background: #eaf7f1;
    font-size: 11px;
    font-style: normal
}

em.parsing {
    color: #a86d19;
    background: #fff4df
}

em.pending {
    color: #6e7890;
    background: #edf0f5
}

@media(max-width:720px) {

    .page-header,
    .toolbar {
        align-items: flex-start;
        flex-direction: column
    }

    .upload-zone {
        align-items: flex-start;
        flex-wrap: wrap
    }

    .upload-zone button {
        margin-left: 53px
    }

    .filters {
        width: 100%
    }

    .filters button {
        flex: 1
    }
}
</style>