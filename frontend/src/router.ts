import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    {
      path: "/dashboard",
      component: () => import("./views/DashboardView.vue"),
      meta: { title: "运行看板" },
    },
    {
      path: "/run",
      component: () => import("./views/RunView.vue"),
      meta: { title: "执行与任务" },
    },
    {
      path: "/logs",
      component: () => import("./views/LogsView.vue"),
      meta: { title: "运行日志" },
    },
    {
      path: "/accounts",
      component: () => import("./views/AccountsView.vue"),
      meta: { title: "账号管理" },
    },
    {
      path: "/messages",
      component: () => import("./views/MessagesView.vue"),
      meta: { title: "消息配置" },
    },
    {
      path: "/auto-schedule",
      component: () => import("./views/AutoScheduleView.vue"),
      meta: { title: "自动计划" },
    },
    {
      path: "/settings",
      component: () => import("./views/SettingsView.vue"),
      meta: { title: "系统设置" },
    },
  ],
});

export default router;
