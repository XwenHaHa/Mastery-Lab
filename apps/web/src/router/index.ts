import { createRouter, createWebHistory } from 'vue-router'

import AppShell from '@/layouts/AppShell.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppShell,
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '概览' },
        },
        {
          path: 'courses',
          name: 'courses',
          component: () => import('@/views/CoursesView.vue'),
          meta: { title: '课程中心' },
        },
        {
          path: 'courses/import',
          name: 'course-import',
          component: () => import('@/views/CourseImportView.vue'),
          meta: { title: '导入教材' },
        },
        {
          path: 'courses/:id(\\d+)',
          name: 'course-detail',
          component: () => import('@/views/CourseDetailView.vue'),
          meta: { title: '课程详情' },
        },
        {
          path: 'models',
          name: 'models',
          component: () => import('@/views/ModelsView.vue'),
          meta: { title: '模型配置' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '设置' },
        },
      ],
    },
    {
      path: '/courses/:id(\\d+)/classroom',
      name: 'classroom',
      component: () => import('@/views/ClassroomView.vue'),
      meta: { title: 'AI 学习教室' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: '页面不存在' },
    },
  ],
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · Mastery Lab` : 'Mastery Lab'
})

export default router
