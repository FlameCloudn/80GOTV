<script setup lang="ts">
import BaseConfirmation from './components/base/BaseConfirmation.vue';
import AppSidebar from './components/AppSidebar.vue';
</script>

<template>
  <div class="flex h-screen bg-background text-text-main">
    <BaseConfirmation />
    <AppSidebar />
    <main class="flex-1 overflow-y-auto custom-scrollbar">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #3f3f46;
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #52525b;
}
</style>
