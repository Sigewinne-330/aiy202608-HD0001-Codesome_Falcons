<template>
  <section class="billing-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">BALANCE & RECHARGE</div>
        <h1>{{ $t('billing.title') }}</h1>
        <p>{{ $t('billing.subtitle') }}</p>
      </div>
    </header>

    <div v-if="loading" class="page-loading">
      <v-progress-circular indeterminate color="primary" size="42" />
    </div>

    <template v-else>
      <!-- 余额总览 -->
      <v-card class="balance-card" rounded="xl" elevation="0">
        <div class="balance-card__copy">
          <span class="section-tag">{{ $t('billing.balance') }}</span>
          <div class="balance-number">
            {{ summary.balance.toLocaleString() }}
            <small>{{ $t('billing.creditsUnit') }}</small>
          </div>
          <p>{{ $t('billing.tokensPerCredit') }}</p>
        </div>
        <div class="balance-stats">
          <div>
            <span>{{ $t('billing.todaySpent') }}</span>
            <strong>-{{ summary.today_spent.toLocaleString() }}</strong>
          </div>
          <div>
            <span>{{ $t('billing.monthSpent') }}</span>
            <strong>-{{ summary.month_spent.toLocaleString() }}</strong>
          </div>
          <div v-if="summary.estimated_days_left">
            <span>{{ $t('billing.estDays') }}</span>
            <strong>{{ $t('billing.days', { n: summary.estimated_days_left }) }}</strong>
          </div>
        </div>
      </v-card>

      <!-- 用量柱状图 -->
      <v-card class="usage-card" rounded="xl" elevation="0">
        <div class="card-title">{{ $t('billing.usageTitle') }}</div>
        <div class="usage-chart">
          <div v-for="item in usageDays" :key="item.date" class="usage-col" :title="`${item.date}: ${item.spent}`">
            <div class="usage-bar-wrap">
              <div class="usage-bar" :style="{ height: barHeight(item.spent) + '%' }" :class="{ 'is-zero': item.spent === 0 }" />
            </div>
            <span class="usage-label">{{ shortDate(item.date) }}</span>
          </div>
        </div>
      </v-card>

      <!-- 充值档位 -->
      <div class="plans-section">
        <div class="card-title">{{ $t('billing.plansTitle') }}</div>
        <div class="plans-grid">
          <button
            v-for="plan in plans"
            :key="plan.code"
            type="button"
            class="plan-card"
            :class="{ 'plan-card--selected': selectedPlan?.code === plan.code, 'plan-card--hot': plan.code === 'p30' }"
            @click="selectedPlan = plan"
          >
            <span v-if="plan.code === 'p30'" class="plan-hot">{{ $t('billing.popular') }}</span>
            <span class="plan-amount">¥{{ plan.amount }}</span>
            <span class="plan-credits">{{ plan.credits.toLocaleString() }} {{ $t('billing.creditsUnit') }}</span>
            <v-icon size="20" color="white" class="plan-check">mdi-check-circle</v-icon>
          </button>
        </div>
        <p class="demo-note">{{ $t('billing.demoNote') }}</p>
      </div>

      <!-- 积分流水 -->
      <v-card class="ledger-card" rounded="xl" elevation="0">
        <div class="card-title">{{ $t('billing.ledgerTitle') }}</div>
        <div v-if="ledger.length" class="ledger-list">
          <div v-for="item in ledger" :key="item.id" class="ledger-item">
            <span class="ledger-icon" :class="`ledger-icon--${item.change_type}`">
              <v-icon :icon="ledgerIcon(item.change_type)" size="18" />
            </span>
            <div class="ledger-copy">
              <strong>{{ ledgerTitle(item) }}</strong>
              <small>{{ ledgerDate(item.created_at) }}</small>
            </div>
            <span class="ledger-amount" :class="`ledger-amount--${item.change_type}`">
              {{ item.change_amount > 0 ? '+' : '' }}{{ item.change_amount.toLocaleString() }}
            </span>
          </div>
        </div>
        <div v-else class="ledger-empty">{{ $t('billing.ledgerEmpty') }}</div>
      </v-card>
    </template>

    <!-- 模拟支付确认 -->
    <v-dialog v-model="payDialog" max-width="420">
      <v-card rounded="xl">
        <v-card-title class="pt-5 px-6">{{ $t('billing.confirmTitle') }}</v-card-title>
        <v-card-text class="px-6 pt-2">
          <div class="pay-summary">
            <span class="pay-amount">¥{{ selectedPlan?.amount }}</span>
            <v-icon icon="mdi-arrow-right" size="22" color="grey" />
            <span class="pay-credits">{{ selectedPlan?.credits.toLocaleString() }} {{ $t('billing.creditsUnit') }}</span>
          </div>
          <p class="pay-desc">{{ $t('billing.confirmDesc', { amount: selectedPlan?.amount, credits: selectedPlan?.credits.toLocaleString() }) }}</p>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="payDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="paying" @click="confirmPay">{{ $t('billing.payNow') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="paySuccess" color="success" timeout="3000">
      {{ $t('billing.paySuccess') }}
    </v-snackbar>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { authFetch } from '@/stores/auth'

const { t } = useI18n()
const loading = ref(true)
const summary = ref({ balance: 0, today_spent: 0, month_spent: 0, estimated_days_left: null })
const usageDays = ref([])
const plans = ref([])
const ledger = ref([])
const selectedPlan = ref(null)
const payDialog = ref(false)
const paying = ref(false)
const paySuccess = ref(false)

const maxSpent = computed(() => Math.max(...usageDays.value.map((d) => d.spent), 1))

function barHeight(spent) {
  return spent === 0 ? 4 : Math.max(8, Math.round((spent / maxSpent.value) * 100))
}

function shortDate(value) {
  if (!value) return ''
  const parts = value.split('-')
  return `${parts[1]}/${parts[2]}`
}

function ledgerIcon(type) {
  return { consume: 'mdi-chart-line', recharge: 'mdi-cash-plus', gift: 'mdi-gift-outline' }[type] || 'mdi-circle-outline'
}

function ledgerTitle(item) {
  if (item.change_type === 'recharge') return t('billing.typeRecharge')
  if (item.change_type === 'gift') return t('billing.typeGift')
  return t('billing.typeConsume')
}

function ledgerDate(value) {
  if (!value) return ''
  return String(value).slice(0, 16).replace('T', ' ')
}

async function loadAll() {
  loading.value = true
  try {
    const [summaryRes, usageRes, plansRes, ledgerRes] = await Promise.all([
      authFetch('/api/billing/summary'),
      authFetch('/api/billing/usage?days=7'),
      authFetch('/api/billing/plans'),
      authFetch('/api/billing/ledger?limit=30'),
    ])
    if (summaryRes.ok) summary.value = await summaryRes.json()
    if (usageRes.ok) usageDays.value = (await usageRes.json()).days || []
    if (plansRes.ok) plans.value = (await plansRes.json()).plans || []
    if (ledgerRes.ok) ledger.value = (await ledgerRes.json()).items || []
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
}

function openPay(plan) {
  selectedPlan.value = plan
  payDialog.value = true
}

async function confirmPay() {
  if (!selectedPlan.value) return
  paying.value = true
  try {
    const createRes = await authFetch(`/api/billing/orders?plan_code=${selectedPlan.value.code}`, { method: 'POST' })
    if (!createRes.ok) throw new Error('create order failed')
    const order = await createRes.json()
    const payRes = await authFetch(`/api/billing/orders/${order.id}/pay`, { method: 'POST' })
    if (!payRes.ok) throw new Error('pay failed')
    payDialog.value = false
    paySuccess.value = true
    await loadAll()
  } catch {
    /* ignore */
  } finally {
    paying.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.billing-page { min-height: calc(100vh - 64px); padding: 28px clamp(22px, 5vw, 70px) 110px; color: #1e2942; background:
  radial-gradient(circle at 12% 5%, rgba(76, 111, 255, 0.10), transparent 28%),
  radial-gradient(circle at 88% 88%, rgba(102, 75, 230, 0.08), transparent 28%),
  #f7f8fc; }
.page-header { margin-bottom: 24px; }
.eyebrow { color: #4a6ce2; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.page-header h1 { margin-top: 4px; font-size: clamp(28px, 3vw, 39px); letter-spacing: -.04em; }
.page-header p { margin-top: 8px; color: #7f899d; font-size: 13px; }
.page-loading { min-height: 60vh; display: grid; place-items: center; }

.balance-card {
  display: flex; align-items: center; justify-content: space-between; gap: 30px; flex-wrap: wrap;
  padding: 30px 32px; border: 1px solid rgba(39, 53, 83, .09);
  background: linear-gradient(120deg, #2e4fd8, #6a4bd4 70%) !important;
  box-shadow: 0 18px 50px rgba(50, 60, 160, .25);
}
.section-tag { display: inline-flex; padding: 4px 10px; border-radius: 999px; background: rgba(255,255,255,.16); color: #fff; font-size: 10px; font-weight: 750; }
.balance-number { margin-top: 14px; color: #fff; font-size: clamp(34px, 4vw, 46px); font-weight: 800; line-height: 1; letter-spacing: -.02em; }
.balance-number small { margin-left: 8px; font-size: 14px; font-weight: 500; opacity: .8; }
.balance-card__copy p { margin-top: 9px; color: rgba(255,255,255,.72); font-size: 12px; }
.balance-stats { display: flex; gap: 12px; flex-wrap: wrap; }
.balance-stats > div { min-width: 108px; padding: 13px 16px; border-radius: 14px; background: rgba(255,255,255,.12); }
.balance-stats span, .balance-stats strong { display: block; }
.balance-stats span { color: rgba(255,255,255,.72); font-size: 10px; }
.balance-stats strong { margin-top: 5px; color: #fff; font-size: 17px; }

.usage-card, .ledger-card { margin-top: 18px; padding: 22px 24px; border: 1px solid rgba(39,53,83,.09); background: rgba(255,255,255,.94) !important; box-shadow: 0 12px 34px rgba(31,44,75,.055); }
.card-title { margin-bottom: 16px; font-size: 15px; font-weight: 750; }
.usage-chart { display: flex; align-items: flex-end; gap: 12px; height: 130px; padding: 6px 4px 0; }
.usage-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 7px; height: 100%; }
.usage-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
.usage-bar { width: 60%; max-width: 26px; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, #6a4bd4, #3f63dd); }
.usage-bar.is-zero { background: #e3e7f0; }
.usage-label { color: #9aa2b1; font-size: 10px; }

.plans-section { margin-top: 22px; }
.plans-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.plan-card { position: relative; display: flex; flex-direction: column; gap: 7px; padding: 20px 16px 17px; border: 1.5px solid #e3e7f0; border-radius: 16px; background: rgba(255,255,255,.94); cursor: pointer; text-align: left; transition: transform .16s, border-color .16s, box-shadow .16s; }
.plan-card:hover { transform: translateY(-3px); }
.plan-card--selected { border-color: #4a6ce2; box-shadow: 0 10px 26px rgba(74,108,226,.18); }
.plan-card--hot { border-color: #e89a3c; }
.plan-amount { font-size: 24px; font-weight: 800; color: #1e2942; }
.plan-credits { font-size: 11.5px; color: #7f899d; }
.plan-check { position: absolute; top: 10px; right: 10px; opacity: 0; transition: opacity .16s; }
.plan-card--selected .plan-check { opacity: 1; }
.plan-hot { position: absolute; top: -9px; left: 14px; padding: 3px 9px; border-radius: 999px; color: #fff; background: #e89a3c; font-size: 9.5px; font-weight: 750; }
.demo-note { margin-top: 12px; color: #a0a7b5; font-size: 11px; }

.ledger-list { display: flex; flex-direction: column; }
.ledger-item { display: flex; align-items: center; gap: 13px; padding: 12px 4px; border-bottom: 1px solid #f0f2f6; }
.ledger-item:last-child { border-bottom: 0; }
.ledger-icon { width: 38px; height: 38px; flex: 0 0 38px; display: grid; place-items: center; border-radius: 12px; }
.ledger-icon--consume { color: #4a6ce2; background: #edf2ff; }
.ledger-icon--recharge { color: #25a572; background: #eaf9f2; }
.ledger-icon--gift { color: #e8891c; background: #fff4e6; }
.ledger-copy { flex: 1; min-width: 0; }
.ledger-copy strong, .ledger-copy small { display: block; }
.ledger-copy strong { font-size: 13px; }
.ledger-copy small { margin-top: 3px; color: #9aa2b1; font-size: 10px; }
.ledger-amount { font-size: 15px; font-weight: 750; }
.ledger-amount--recharge, .ledger-amount--gift { color: #25a572; }
.ledger-amount--consume { color: #de4555; }
.ledger-empty { padding: 36px; text-align: center; color: #9aa2b1; font-size: 12px; }

.pay-summary { display: flex; align-items: center; justify-content: center; gap: 18px; padding: 22px 0; }
.pay-amount { font-size: 30px; font-weight: 800; color: #2e4fd8; }
.pay-credits { font-size: 22px; font-weight: 750; color: #25a572; }
.pay-desc { text-align: center; color: #7f899d; font-size: 12px; }

@media (max-width: 800px) {
  .billing-page { padding: 20px 14px 110px; }
  .plans-grid { grid-template-columns: 1fr 1fr; }
  .balance-stats { width: 100%; }
}
@media (max-width: 480px) {
  .plans-grid { grid-template-columns: 1fr; }
}
</style>
