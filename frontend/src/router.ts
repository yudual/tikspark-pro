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
      path: "/engine-status",
      component: () => import("./views/EngineStatusView.vue"),
      meta: { title: "调度引擎状态" },
    },
    {
      path: "/auto-schedule",
      component: () => import("./views/AutoScheduleView.vue"),
      meta: { title: "自动续火花计划" },
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
      path: "/manual-run",
      component: () => import("./views/ManualRunView.vue"),
      meta: { title: "手动执行" },
    },
    {
      path: "/tasks",
      component: () => import("./views/TasksView.vue"),
      meta: { title: "任务中心" },
    },
    {
      path: "/logs",
      component: () => import("./views/LogsView.vue"),
      meta: { title: "任务日志" },
    },
  ],
});

export default router;
