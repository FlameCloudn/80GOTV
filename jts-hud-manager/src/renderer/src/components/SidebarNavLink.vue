<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const props = defineProps<{
  to: string;
  label: string;
  collapsed: boolean;
  badge?: boolean;
}>();

const route = useRoute();

const isActive = computed(() => {
  return route.path === props.to;
});
</script>

<template>
  <router-link
    :to="to"
    class="flex items-center rounded-lg text-sm font-semibold text-zinc-400 transition-all duration-150 hover:text-text-main hover:bg-zinc-800"
    :class="collapsed ? 'justify-center px-0 py-2.5' : 'gap-3 px-3 py-2.5'"
    active-class="text-text-main! bg-zinc-800 shadow-sm"
    :title="collapsed ? label : undefined"
  >
    <div class="relative flex items-center justify-center w-5 h-5 shrink-0" :class="isActive && '[&>svg]:fill-primary'">
      <slot />
      <span v-if="badge && collapsed" class="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
    </div>
    <span v-if="!collapsed">{{ label }}</span>
    <span v-if="badge && !collapsed" class="ml-auto w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shrink-0"></span>
  </router-link>
</template>
