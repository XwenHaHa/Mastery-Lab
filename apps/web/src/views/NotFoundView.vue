<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <p class="code">404</p>
    <h1>这个页面不存在</h1>
    <p class="desc">可能地址输错了，或者该功能还没有实现（P0 只交付概览、模型配置与设置）。</p>
    <el-button type="primary" @click="router.push({ name: 'dashboard' })">返回概览</el-button>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 10px;
  padding: 40px;
  text-align: center;
}

.code {
  font-family: var(--ml-font-mono);
  font-size: 13px;
  letter-spacing: 0.3em;
  color: var(--ml-text-3);
}

h1 {
  font-size: 20px;
}

.desc {
  color: var(--ml-text-3);
  font-size: 13px;
  max-width: 46ch;
  margin-bottom: 8px;
}
</style>
