<template>
  <section aria-labelledby="memory-center-title">
    <div class="memory-heading">
      <div>
        <h2 id="memory-center-title">{{ $t('personalization.memoryCenterTitle') }}</h2>
        <p>{{ $t('personalization.memoryCenterSubtitle') }}</p>
      </div>
      <v-btn variant="outlined" prepend-icon="mdi-download-outline" @click="downloadExport">
        {{ $t('personalization.export') }}
      </v-btn>
    </div>

    <div class="filters" role="search" :aria-label="$t('personalization.filterMemory')">
      <v-text-field
        v-model="filters.search"
        :label="$t('common.search')"
        prepend-inner-icon="mdi-magnify"
        density="compact"
        variant="outlined"
        hide-details
        clearable
        @keyup.enter="load(true)"
      />
      <v-select v-model="filters.tier" :items="tierOptions" :label="$t('personalization.tier')" density="compact" variant="outlined" hide-details clearable />
      <v-select v-model="filters.source" :items="sourceOptions" :label="$t('personalization.source')" density="compact" variant="outlined" hide-details clearable />
      <v-select v-model="filters.status" :items="statusOptions" :label="$t('personalization.status')" density="compact" variant="outlined" hide-details />
      <v-btn icon="mdi-refresh" variant="text" :aria-label="$t('personalization.refreshMemory')" @click="load(true)" />
    </div>

    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
      {{ error }}
      <template #append><v-btn size="small" variant="text" @click="load(true)">{{ $t('common.retry') }}</v-btn></template>
    </v-alert>
    <v-skeleton-loader v-if="loading" type="list-item-three-line@4" />

    <div v-else-if="!items.length" class="empty-state">
      <v-icon icon="mdi-brain" size="42" />
      <strong>{{ $t('personalization.memoryEmptyTitle') }}</strong>
      <span>{{ $t('personalization.memoryEmptyDesc') }}</span>
    </div>

    <div v-else class="memory-list">
      <article v-for="item in items" :key="item.memory_id" class="memory-card">
        <div class="memory-card__top">
          <div class="chips">
            <v-chip size="x-small" variant="tonal" color="primary">{{ tierLabel(item.tier) }}</v-chip>
            <v-chip size="x-small" variant="outlined">{{ sourceLabel(item.source) }}</v-chip>
            <v-chip size="x-small" variant="outlined">{{ statusLabel(item.status) }}</v-chip>
          </div>
          <div class="memory-actions">
            <v-btn
              v-if="item.editable"
              icon="mdi-pencil-outline"
              size="small"
              variant="text"
              :aria-label="$t('personalization.editMemory')"
              @click="openEdit(item)"
            />
            <v-btn
              v-if="item.deletable"
              icon="mdi-delete-outline"
              color="error"
              size="small"
              variant="text"
              :aria-label="$t('personalization.deleteMemory')"
              @click="remove(item)"
            />
          </div>
        </div>
        <h3>{{ item.display_text }}</h3>
        <div class="memory-meta">
          <span>{{ $t('personalization.evidenceCount', { n: item.evidence_count }) }}</span>
          <span v-if="item.confidence != null">{{ $t('personalization.confidence', { value: percent(item.confidence) }) }}</span>
          <span>{{ dateRange(item) }}</span>
        </div>
      </article>
      <v-btn v-if="nextCursor" block variant="text" :loading="loadingMore" @click="load(false)">
        {{ $t('common.loadMore') }}
      </v-btn>
    </div>

    <div class="danger-zone">
      <div>
        <strong>{{ $t('personalization.resetTitle') }}</strong>
        <p>{{ $t('personalization.resetDesc') }}</p>
        <small>{{ $t('personalization.deletionState', { state: deletionStateLabel }) }}</small>
      </div>
      <v-checkbox v-model="rebuild" :label="$t('personalization.rebuildAfterReset')" hide-details density="compact" />
      <v-btn color="error" variant="outlined" :loading="resetting" @click="resetModel">
        {{ $t('personalization.reset') }}
      </v-btn>
    </div>

    <v-dialog v-model="editOpen" max-width="620">
      <v-card>
        <v-card-title>{{ $t('personalization.editExplicitMemory') }}</v-card-title>
        <v-card-text>
          <v-textarea v-model="editText" :label="$t('personalization.memoryContent')" counter="1000" />
          <div class="date-grid">
            <v-text-field v-model="editFrom" type="date" :label="$t('personalization.validFrom')" />
            <v-text-field v-model="editUntil" type="date" :label="$t('personalization.validUntil')" />
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="editing" :disabled="!editText.trim()" @click="saveEdit">{{ $t('common.save') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { personalizationApi } from '@/services/personalization'

const { t, te } = useI18n()
const filters = reactive({ search: '', tier: '', source: '', status: 'current' })
const items = ref([])
const nextCursor = ref(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')
const deletionState = ref('unknown')
const rebuild = ref(false)
const resetting = ref(false)
const editOpen = ref(false)
const editing = ref(false)
const editItem = ref(null)
const editText = ref('')
const editFrom = ref('')
const editUntil = ref('')

const option = (group, values) => values.map((value) => ({ title: t(`personalization.${group}.${value}`), value }))
const tierOptions = computed(() => option('memoryTier', ['explicit_declaration', 'llm_reflection', 'temporary_context']))
const sourceOptions = computed(() => option('memorySource', ['user', 'llm', 'session']))
const statusOptions = computed(() => option('memoryStatus', ['current', 'deleted', 'superseded', 'expired', 'contradicted']))

function translated(group, value) {
  const key = `personalization.${group}.${value || 'unknown'}`
  return te(key) ? t(key) : (value || t('personalization.unknown'))
}
const tierLabel = (value) => translated('memoryTier', value)
const sourceLabel = (value) => translated('memorySource', value)
const statusLabel = (value) => translated('memoryStatus', value)
const deletionStateLabel = computed(() => translated('deletionStatus', deletionState.value))
const percent = (value) => `${Math.round(Number(value) * 100)}%`
const dateRange = (item) => item.valid_from || item.valid_until
  ? t('personalization.memoryDateRange', { from: item.valid_from || t('personalization.earliest'), until: item.valid_until || t('personalization.ongoing') })
  : t('personalization.longTerm')

async function load(reset = true) {
  if (reset) {
    loading.value = true
    items.value = []
    nextCursor.value = null
  } else loadingMore.value = true
  error.value = ''
  try {
    const result = await personalizationApi.memories({ ...filters, before: reset ? '' : nextCursor.value, limit: 30 })
    items.value = reset ? result.items : [...items.value, ...result.items]
    nextCursor.value = result.next_cursor
  } catch (err) {
    error.value = err?.message || t('personalization.loadMemoryFailed')
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function openEdit(item) {
  editItem.value = item
  editText.value = item.display_text
  editFrom.value = item.valid_from || ''
  editUntil.value = item.valid_until || ''
  editOpen.value = true
}

async function saveEdit() {
  editing.value = true
  error.value = ''
  try {
    await personalizationApi.editMemory(editItem.value.memory_id, {
      display_text: editText.value,
      valid_from: editFrom.value || null,
      valid_until: editUntil.value || null,
    })
    editOpen.value = false
    await load(true)
  } catch (err) {
    error.value = err?.message || t('personalization.editMemoryFailed')
  } finally {
    editing.value = false
  }
}

async function remove(item) {
  if (!window.confirm(t('personalization.deleteMemoryConfirm'))) return
  try {
    await personalizationApi.deleteMemory(item.memory_id)
    await Promise.all([load(true), loadDeletionStatus()])
  } catch (err) {
    error.value = err?.message || t('personalization.deleteMemoryFailed')
  }
}

async function downloadExport() {
  try {
    const data = await personalizationApi.exportMemory()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `ibuddy-personalization-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = err?.message || t('personalization.exportFailed')
  }
}

async function resetModel() {
  if (!window.confirm(t('personalization.resetConfirm'))) return
  resetting.value = true
  error.value = ''
  try {
    const settings = await personalizationApi.settings()
    await personalizationApi.reset(settings, rebuild.value)
    await Promise.all([load(true), loadDeletionStatus()])
  } catch (err) {
    error.value = err?.message || t('personalization.resetFailed')
  } finally {
    resetting.value = false
  }
}

async function loadDeletionStatus() {
  try {
    deletionState.value = (await personalizationApi.deletionStatus()).state
  } catch {
    deletionState.value = 'unknown'
  }
}

let filterTimer
watch(() => [filters.tier, filters.source, filters.status], () => load(true))
watch(() => filters.search, () => {
  clearTimeout(filterTimer)
  filterTimer = window.setTimeout(() => load(true), 300)
})
onMounted(() => { load(true); loadDeletionStatus() })
onBeforeUnmount(() => clearTimeout(filterTimer))
</script>

<style scoped>
.memory-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--ib-border); }
.memory-heading h2 { margin: 0; color: var(--ib-text); font-size: 21px; }
.memory-heading p { margin: 5px 0 0; color: var(--ib-text-secondary); font-size: 12px; }
.filters { display: grid; grid-template-columns: minmax(160px, 1.5fr) repeat(3, minmax(120px, 1fr)) auto; gap: 8px; margin: 18px 0; }
.memory-list { display: grid; gap: 10px; }
.memory-card { padding: 15px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); }
.memory-card__top { display: flex; justify-content: space-between; gap: 10px; }
.chips, .memory-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.memory-card h3 { margin: 10px 0 8px; color: var(--ib-text); font-size: 14px; line-height: 1.55; }
.memory-meta { display: flex; flex-wrap: wrap; gap: 14px; color: var(--ib-text-muted); font-size: 11px; }
.empty-state { display: grid; min-height: 280px; justify-items: center; align-content: center; gap: 7px; padding: 32px 20px; color: var(--ib-text-secondary); text-align: center; }
.empty-state strong { color: var(--ib-text); }
.danger-zone { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 14px; margin-top: 28px; padding: 16px; border: 1px solid color-mix(in srgb, var(--ib-danger) 30%, var(--ib-border)); border-radius: var(--ib-radius-md); background: color-mix(in srgb, var(--ib-danger) 5%, var(--ib-surface)); }
.danger-zone strong { color: var(--ib-text); }
.danger-zone p { margin: 4px 0; color: var(--ib-text-secondary); font-size: 12px; }
.danger-zone small { color: var(--ib-text-muted); }
.date-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 800px) { .filters { grid-template-columns: 1fr 1fr; } .filters > :first-child { grid-column: 1 / -1; } .danger-zone { grid-template-columns: 1fr; } }
@media (max-width: 520px) { .memory-heading { flex-direction: column; } .filters, .date-grid { grid-template-columns: 1fr; } .filters > :first-child { grid-column: auto; } }
</style>
