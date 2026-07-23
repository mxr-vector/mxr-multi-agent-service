<script setup lang="ts">
const categories = [
    { name: '产品文档', description: '产品功能、版本说明与操作手册', documents: 96, color: '#6279df' },
    { name: '服务规范', description: '客户支持、工单处理与服务标准', documents: 74, color: '#40a67b' },
    { name: '技术方案', description: '架构设计、接口文档与技术沉淀', documents: 138, color: '#a276d7' },
    { name: '培训资料', description: '入职培训、内部分享与学习资料', documents: 52, color: '#df9b4f' },
]
</script>

<template>
    <section class="categories-page">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / CATEGORIES</p>
                <h1>分类管理</h1>
                <p>使用分类组织文档，让检索范围更清晰、更可控。</p>
            </div><button class="primary-button" type="button">＋ 新建分类</button>
        </header>
        <section class="category-intro"><span>⌘</span>
            <div><strong>分类是文档的检索标签</strong>
                <p>为文档分配分类后，可在智能体检索时按业务范围筛选内容。</p>
            </div>
        </section>
        <section class="category-grid">
            <article v-for="category in categories" :key="category.name" class="category-card"><span
                    class="category-mark" :style="{ background: category.color }"></span>
                <div class="card-heading">
                    <h2>{{ category.name }}</h2><button type="button" aria-label="更多操作">•••</button>
                </div>
                <p>{{ category.description }}</p>
                <footer><strong>{{ category.documents }}</strong><span>份文档</span><button type="button">查看文档 →</button>
                </footer>
            </article>
        </section>
    </section>
</template>

<style scoped>
.categories-page {
    display: grid;
    gap: 24px;
    max-width: 1280px;
    margin: 0 auto;
    color: #273249
}

.page-header {
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

.category-intro {
    display: flex;
    align-items: center;
    gap: 13px;
    padding: 17px 19px;
    border: 1px solid #dfe5f9;
    border-radius: 12px;
    background: #f4f6ff
}

.category-intro>span {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 9px;
    color: #526ae2;
    background: #e3e8ff
}

.category-intro strong {
    font-size: 13px
}

.category-intro p {
    margin: 4px 0 0;
    color: #728098;
    font-size: 12px
}

.category-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px
}

.category-card {
    position: relative;
    padding: 22px;
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
}

.category-mark {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 4px
}

.card-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px
}

.card-heading h2 {
    margin-bottom: 0;
    font-size: 16px
}

.card-heading button {
    border: 0;
    color: #8993a5;
    background: transparent;
    letter-spacing: 1px
}

.category-card>p {
    min-height: 39px;
    margin: 13px 0 20px;
    color: #788397;
    font-size: 13px;
    line-height: 1.5
}

.category-card footer {
    display: flex;
    align-items: baseline;
    gap: 5px;
    padding-top: 15px;
    border-top: 1px solid #eff1f5
}

.category-card footer strong {
    font-size: 21px
}

.category-card footer span {
    color: #8993a5;
    font-size: 12px
}

.category-card footer button {
    margin-left: auto;
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600
}

@media(max-width:720px) {
    .page-header {
        align-items: flex-start;
        flex-direction: column
    }

    .category-grid {
        grid-template-columns: 1fr
    }
}
</style>