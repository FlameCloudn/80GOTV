<script setup lang="ts">
// 小角标：颜色名和旧版一样（amber / zinc / blue / orange / emerald / red）
withDefaults(defineProps<{ variant?: 'amber' | 'zinc' | 'blue' | 'orange' | 'emerald' | 'red' }>(), {
  variant: 'zinc'
})

const TAG_CLASS: Record<string, string> = {
  amber: 'tag-warn',
  zinc: '',
  blue: 'tag-ct',
  orange: 'tag-t',
  emerald: 'tag-ok',
  red: 'tag-bad'
}
</script>

<template>
  <span class="tag" :class="TAG_CLASS[variant]"><slot /></span>
</template>
