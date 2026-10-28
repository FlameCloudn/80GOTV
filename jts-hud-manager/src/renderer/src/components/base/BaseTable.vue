<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import AppIcon from '../ui/AppIcon.vue';

const props = withDefaults(defineProps<{
  headers: { key: string; label: string; sortable?: boolean }[];
  items: any[];
  isLoading?: boolean;
  selectable?: boolean;
  sortKey?: string;
  sortDir?: 'asc' | 'desc';
  defaultPageSize?: number;
  searchPlaceholder?: string;
  searchable?: boolean;
}>(), {
  isLoading: false,
  selectable: false,
  sortDir: 'asc',
  defaultPageSize: 10,
  searchPlaceholder: '搜索...',
  searchable: true
});

const emit = defineEmits<{
  (e: 'edit', item: any): void;
  (e: 'delete', id: string): void;
  (e: 'sort', payload: { key: string; dir: 'asc' | 'desc' }): void;
  (e: 'selection-change', ids: string[]): void;
}>();

// --- SEARCH ---
const searchQuery = ref('');

const filteredItems = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return props.items;
  const keys = props.headers.map(h => h.key);
  return props.items.filter(item =>
    keys.some(key => {
      const val = item[key];
      return val != null && String(val).toLowerCase().includes(q);
    })
  );
});

// --- PAGINATION ---
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const pageSize = ref(props.defaultPageSize);
const currentPage = ref(1);

const totalPages = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / pageSize.value)));

const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredItems.value.slice(start, start + pageSize.value);
});

// Visible page numbers — show up to 5 around current
const visiblePages = computed(() => {
  const total = totalPages.value;
  const cur = currentPage.value;
  const delta = 2;
  const pages: (number | '…')[] = [];
  const lo = Math.max(1, cur - delta);
  const hi = Math.min(total, cur + delta);
  if (lo > 1) { pages.push(1); if (lo > 2) pages.push('…'); }
  for (let i = lo; i <= hi; i++) pages.push(i);
  if (hi < total) { if (hi < total - 1) pages.push('…'); pages.push(total); }
  return pages;
});

// Reset to page 1 when items list, filter, or page size changes
watch(() => props.items.length, () => { currentPage.value = 1; });
watch(pageSize, () => { currentPage.value = 1; });
watch(searchQuery, () => { currentPage.value = 1; });

// --- SELECTION ---
const selectedIds = ref<string[]>([]);

watch(() => props.items, () => {
  selectedIds.value = [];
  emit('selection-change', []);
});

const allSelected = computed(() =>
  filteredItems.value.length > 0 && filteredItems.value.every(i => selectedIds.value.includes(i._id || i.id))
);

const someSelected = computed(() => {
  const filtered = filteredItems.value;
  const count = filtered.filter(i => selectedIds.value.includes(i._id || i.id)).length;
  return count > 0 && count < filtered.length;
});

const toggleSelectAll = () => {
  const filteredIds = filteredItems.value.map(i => i._id || i.id);
  if (allSelected.value) {
    selectedIds.value = selectedIds.value.filter(id => !filteredIds.includes(id));
  } else {
    const merged = new Set([...selectedIds.value, ...filteredIds]);
    selectedIds.value = [...merged];
  }
  emit('selection-change', [...selectedIds.value]);
};

const toggleSelectItem = (id: string) => {
  const idx = selectedIds.value.indexOf(id);
  if (idx === -1) selectedIds.value.push(id);
  else selectedIds.value.splice(idx, 1);
  emit('selection-change', [...selectedIds.value]);
};

const isSelected = (id: string) => selectedIds.value.includes(id);

// --- SORT ---
const handleSort = (header: { key: string; sortable?: boolean }) => {
  if (!header.sortable) return;
  const newDir = props.sortKey === header.key && props.sortDir === 'asc' ? 'desc' : 'asc';
  emit('sort', { key: header.key, dir: newDir });
};
</script>

<template>
  <div class="panel table-panel">
    <div v-if="searchable" class="table-search">
      <AppIcon name="search" class="search-icon" />
      <input v-model="searchQuery" type="text" class="input search-input" :placeholder="searchPlaceholder" />
      <button v-if="searchQuery" type="button" class="search-clear" title="清空搜索" @click="searchQuery = ''">
        <AppIcon name="x" />
      </button>
    </div>

    <div v-if="isLoading" class="table-state">正在加载数据…</div>

    <div v-else-if="filteredItems.length === 0" class="table-state">
      <span v-if="searchQuery">没有找到与“<b>{{ searchQuery }}</b>”相关的结果。</span>
      <span v-else>暂无记录。</span>
    </div>

    <div v-else class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th v-if="selectable" class="col-check">
              <input
                type="checkbox"
                class="check"
                :checked="allSelected"
                :indeterminate="someSelected"
                title="全选"
                @change="toggleSelectAll"
              />
            </th>
            <th
              v-for="header in headers"
              :key="header.key"
              :class="{ sortable: header.sortable, sorted: sortKey === header.key }"
              @click="handleSort(header)"
            >
              <span class="th-inner">
                {{ header.label }}
                <AppIcon v-if="sortKey === header.key" name="chevronDown" class="sort-icon" :class="{ asc: sortDir === 'asc' }" />
              </span>
            </th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in pagedItems"
            :key="item._id"
            :class="{ selected: selectable && isSelected(item._id || item.id) }"
          >
            <td v-if="selectable" class="col-check">
              <input
                type="checkbox"
                class="check"
                :checked="isSelected(item._id || item.id)"
                @change="toggleSelectItem(item._id || item.id)"
              />
            </td>
            <td v-for="header in headers" :key="header.key">
              <slot :name="`cell-${header.key}`" :item="item">{{ item[header.key] }}</slot>
            </td>
            <td class="col-actions">
              <div class="row-actions">
                <slot name="row-actions" :item="item" />
                <button type="button" class="icon-btn" title="编辑" @click="$emit('edit', item)"><AppIcon name="edit" /></button>
                <button type="button" class="icon-btn danger" title="删除" @click="$emit('delete', item._id || item.id)"><AppIcon name="trash" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!isLoading && filteredItems.length > 0" class="table-foot">
      <div class="page-size">
        <span>每页</span>
        <select v-model="pageSize" class="select select-sm" aria-label="每页显示多少条">
          <option v-for="opt in PAGE_SIZE_OPTIONS" :key="opt" :value="opt">{{ opt }}</option>
        </select>
        <span class="num total">共 {{ filteredItems.length }} 条</span>
      </div>
      <div class="pager">
        <button type="button" class="icon-btn" :disabled="currentPage === 1" title="上一页" @click="currentPage--"><AppIcon name="chevronLeft" /></button>
        <template v-for="p in visiblePages" :key="p">
          <span v-if="p === '…'" class="pager-gap">…</span>
          <button v-else type="button" class="pager-num num" :class="{ active: currentPage === p }" @click="currentPage = p as number">{{ p }}</button>
        </template>
        <button type="button" class="icon-btn" :disabled="currentPage === totalPages" title="下一页" @click="currentPage++"><AppIcon name="chevronRight" /></button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.table-panel { overflow: hidden; }
.table-search { position: relative; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.search-icon { position: absolute; left: 25px; top: 50%; transform: translateY(-50%); color: var(--text-3); pointer-events: none; }
.search-input { padding-left: 34px; padding-right: 34px; }
.search-clear { position: absolute; right: 22px; top: 50%; transform: translateY(-50%); width: 22px; height: 22px; display: grid; place-items: center; border: none; border-radius: var(--radius-sm); background: transparent; color: var(--text-3); }
.search-clear:hover { background: var(--bg-hover); color: var(--text); }
.search-clear .icon { width: 13px; height: 13px; }
.table-state { padding: 40px 20px; text-align: center; color: var(--text-3); }
.table-state b { color: var(--text); }
.table-scroll { overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; text-align: left; }
.table th { height: 38px; padding: 0 12px; font-size: 12px; font-weight: 600; color: var(--text-3); border-bottom: 1px solid var(--border); white-space: nowrap; }
.table th.sortable { cursor: pointer; user-select: none; }
.table th.sortable:hover, .table th.sorted { color: var(--text); }
.th-inner { display: inline-flex; align-items: center; gap: 4px; }
.sort-icon { width: 12px; height: 12px; color: var(--accent); }
.sort-icon.asc { transform: rotate(180deg); }
.table td { height: 52px; padding: 0 12px; font-size: 13px; color: var(--text-2); border-bottom: 1px solid var(--border); }
.table tbody tr:last-child td { border-bottom: none; }
.table tbody tr:hover { background: var(--bg-hover); }
.table tbody tr.selected { background: var(--accent-soft); }
.col-check { width: 40px; padding-left: 16px !important; padding-right: 0 !important; }
.check { width: 14px; height: 14px; accent-color: var(--accent); cursor: pointer; }
.col-actions { text-align: right; width: 1%; white-space: nowrap; }
.row-actions { display: inline-flex; align-items: center; gap: 6px; }
.table-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-top: 1px solid var(--border); background: var(--bg-raised); }
.page-size { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); }
.select-sm { width: 70px; height: 28px; font-size: 12px; }
.pager { display: flex; align-items: center; gap: 4px; }
.pager-gap { padding: 0 4px; color: var(--text-3); }
.pager-num { min-width: 30px; height: 30px; padding: 0 6px; border-radius: var(--radius-md); border: 1px solid transparent; background: transparent; color: var(--text-2); font-size: 12px; font-weight: 600; }
.pager-num:hover { background: var(--bg-hover); color: var(--text); }
.pager-num.active { background: var(--accent-soft); border-color: rgba(107, 159, 209, 0.45); color: var(--accent); }
</style>
