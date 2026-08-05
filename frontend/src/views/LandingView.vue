<template>
  <div class="landing-page">
    <!-- ================= 顶部导航 ================= -->
    <header class="landing-nav">
      <div class="landing-nav-inner">
        <router-link to="/" class="brand-button" aria-label="IBuddy">
          <span class="brand-mark">IB</span>
          <span class="brand-copy">
            <strong>IBuddy</strong>
            <small>{{ $t('landing.slogan') }}</small>
          </span>
        </router-link>

        <div class="nav-actions">
          <v-menu>
            <template #activator="{ props }">
              <v-btn
                v-bind="props"
                variant="text"
                color="primary"
                rounded="lg"
                prepend-icon="mdi-translate"
              >
                {{ currentLanguageLabel }}
              </v-btn>
            </template>
            <v-list density="compact" min-width="160">
              <v-list-item
                v-for="opt in languageOptions"
                :key="opt.value"
                :active="opt.value === currentLocale"
                @click="changeLanguage(opt.value)"
              >
                <v-list-item-title class="text-body-2">{{ opt.title }}</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-menu>
          <v-btn v-if="isAuthenticated" color="primary" rounded="lg" to="/calendar" class="nav-register">
            <v-icon start>mdi-view-dashboard</v-icon>
            {{ $t('landing.enterApp') }}
          </v-btn>
          <template v-else>
            <v-btn variant="text" color="primary" rounded="lg" to="/login">{{ $t('landing.login') }}</v-btn>
            <v-btn color="primary" rounded="lg" to="/register" class="nav-register">{{ $t('landing.startFree') }}</v-btn>
          </template>
        </div>
      </div>
    </header>

    <main>
      <!-- ================= Hero ================= -->
      <section class="hero">
        <div class="hero-inner">
          <div class="hero-copy">
            <v-chip
              class="hero-chip"
              color="primary"
              variant="tonal"
              size="small"
              prepend-icon="mdi-rocket-launch-outline"
            >
              {{ $t('landing.badge') }}
            </v-chip>

            <h1 class="hero-title">
              {{ $t('landing.title1') }}<br />
              <span class="gradient-text">{{ $t('landing.title2') }}</span>
            </h1>

            <p class="hero-sub">{{ $t('landing.subtitle') }}</p>

            <div class="hero-actions">
              <v-btn
                v-if="isAuthenticated"
                size="x-large"
                color="primary"
                rounded="lg"
                to="/calendar"
                class="hero-cta"
                elevation="4"
              >
                {{ $t('landing.enterApp') }}
                <v-icon end>mdi-arrow-right</v-icon>
              </v-btn>
              <v-btn
                v-else
                size="x-large"
                color="primary"
                rounded="lg"
                to="/register"
                class="hero-cta"
                elevation="4"
              >
                {{ $t('landing.startNow') }}
                <v-icon end>mdi-arrow-right</v-icon>
              </v-btn>
              <v-btn
                size="x-large"
                variant="outlined"
                color="primary"
                rounded="lg"
                @click="scrollToId('#features')"
              >
                {{ $t('landing.learnMore') }}
              </v-btn>
            </div>

            <div class="hero-points">
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>{{ $t('landing.point1') }}</span>
              </div>
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>{{ $t('landing.point2') }}</span>
              </div>
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>{{ $t('landing.point3') }}</span>
              </div>
            </div>
          </div>

          <!-- 产品预览卡片 -->
          <div class="hero-visual" aria-hidden="true">
            <div class="mock-window">
              <div class="mock-window-bar">
                <span class="mock-dot red"></span>
                <span class="mock-dot yellow"></span>
                <span class="mock-dot green"></span>
                <span class="mock-window-title">{{ $t('landing.windowTitle') }}</span>
              </div>

              <!-- 月历网格（7×4 = 28 天） -->
              <div class="mock-month">
                <div class="mock-weekday" v-for="d in mockWeekDays" :key="d">{{ d }}</div>
                <div
                  v-for="i in 28"
                  :key="i"
                  class="mock-day-cell"
                  :class="{ 'mock-today': i === 9 }"
                >
                  <span class="mock-day-num">{{ i }}</span>
                  <!-- 示例任务标记 -->
                  <span v-if="i === 9" class="mock-pill mock-pill-blue"></span>
                  <span v-if="i === 9" class="mock-pill mock-pill-deadline"></span>
                  <span v-if="i === 14" class="mock-pill mock-pill-teal"></span>
                  <span v-if="i === 18" class="mock-pill mock-pill-blue"></span>
                  <span v-if="i === 21" class="mock-pill mock-pill-deadline"></span>
                </div>
              </div>

              <!-- 图例 -->
              <div class="mock-legend">
                <span><i class="l-todo" /> Todo</span>
                <span><i class="l-process" /> Process</span>
                <span><i class="l-deadline" /> DDL</span>
              </div>
            </div>

            <!-- 浮动 AI 对话气泡 -->
            <div class="mock-chat-bubble">
              <div class="mock-chat-header">
                <v-icon size="14" color="#3265F5">mdi-creation-outline</v-icon>
                <span>IBuddy</span>
              </div>
              <div class="mock-chat-body">
                <p>{{ $t('landing.chatPreview') }}</p>
              </div>
              <div class="mock-chat-input">
                <span>{{ $t('landing.chatPlaceholder') }}</span>
                <v-icon size="14" color="#3265F5">mdi-send</v-icon>
              </div>
            </div>

            <div class="hero-visual-glow"></div>
          </div>
        </div>
      </section>

      <!-- ================= 功能特性 ================= -->
      <section id="features" class="section">
        <div class="section-inner">
          <div class="section-head">
            <v-chip color="secondary" variant="tonal" size="small" class="mb-3">
              {{ $t('landing.featuresTag') }}
            </v-chip>
            <h2 class="section-title">{{ $t('landing.featuresTitle') }}</h2>
            <p class="section-sub">{{ $t('landing.featuresSub') }}</p>
          </div>

          <v-row class="feature-grid" dense>
            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-blue">
                  <v-icon size="26" color="#3265F5">mdi-creation-outline</v-icon>
                </div>
                <h3>{{ $t('landing.f1Title') }}</h3>
                <p>{{ $t('landing.f1Desc') }}</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-purple">
                  <v-icon size="26" color="#7348E8">mdi-sitemap-outline</v-icon>
                </div>
                <h3>{{ $t('landing.f2Title') }}</h3>
                <p>{{ $t('landing.f2Desc') }}</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-teal">
                  <v-icon size="26" color="#26A69A">mdi-lightning-bolt-outline</v-icon>
                </div>
                <h3>{{ $t('landing.f3Title') }}</h3>
                <p>{{ $t('landing.f3Desc') }}</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-orange">
                  <v-icon size="26" color="#FF7043">mdi-calendar-month-outline</v-icon>
                </div>
                <h3>{{ $t('landing.f4Title') }}</h3>
                <p>{{ $t('landing.f4Desc') }}</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-pink">
                  <v-icon size="26" color="#E91E63">mdi-bell-outline</v-icon>
                </div>
                <h3>{{ $t('landing.f5Title') }}</h3>
                <p>{{ $t('landing.f5Desc') }}</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="4">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-cyan">
                  <v-icon size="26" color="#00BCD4">mdi-scale-balance</v-icon>
                </div>
                <h3>{{ $t('landing.f6Title') }}</h3>
                <p>{{ $t('landing.f6Desc') }}</p>
              </v-card>
            </v-col>
          </v-row>
        </div>
      </section>

      <!-- ================= 使用流程 ================= -->
      <section id="how" class="section section-alt">
        <div class="section-inner">
          <div class="section-head">
            <v-chip color="accent" variant="tonal" size="small" class="mb-3">
              {{ $t('landing.howTag') }}
            </v-chip>
            <h2 class="section-title">{{ $t('landing.howTitle') }}</h2>
            <p class="section-sub">{{ $t('landing.howSub') }}</p>
          </div>

          <v-row class="how-grid">
            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">01</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-message-text-outline</v-icon>
                </div>
                <h3>{{ $t('landing.h1Title') }}</h3>
                <p>{{ $t('landing.h1Desc') }}</p>
              </div>
            </v-col>

            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">02</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-calendar-clock-outline</v-icon>
                </div>
                <h3>{{ $t('landing.h2Title') }}</h3>
                <p>{{ $t('landing.h2Desc') }}</p>
              </div>
            </v-col>

            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">03</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-bell-ring-outline</v-icon>
                </div>
                <h3>{{ $t('landing.h3Title') }}</h3>
                <p>{{ $t('landing.h3Desc') }}</p>
              </div>
            </v-col>
          </v-row>
        </div>
      </section>

      <!-- ================= CTA ================= -->
      <section class="section">
        <div class="section-inner">
          <v-card class="cta-card" rounded="xl" elevation="0">
            <div class="cta-inner">
              <h2>{{ $t('landing.ctaTitle') }}</h2>
              <p>{{ $t('landing.ctaSub') }}</p>
              <v-btn
                size="x-large"
                color="white"
                rounded="lg"
                class="cta-btn"
                :to="isAuthenticated ? '/calendar' : '/register'"
              >
                <v-icon start>mdi-rocket-launch</v-icon>
                {{ isAuthenticated ? $t('landing.enterApp') : $t('landing.ctaBtn') }}
              </v-btn>
            </div>
          </v-card>
        </div>
      </section>
    </main>

    <!-- ================= Footer ================= -->
    <footer class="landing-footer">
      <div class="landing-footer-inner">
        <div class="brand-button" style="cursor: default;">
          <span class="brand-mark">IB</span>
          <span class="brand-copy">
            <strong>IBuddy</strong>
            <small>{{ $t('landing.slogan') }}</small>
          </span>
        </div>
        <p>{{ $t('landing.footer') }}</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale, LOCALE_NAMES, SUPPORTED_LOCALES } from '@/i18n'
import { useAuth } from '@/stores/auth'

const { locale } = useI18n()
const { isAuthenticated } = useAuth()

const currentLocale = computed(() => locale.value)
const currentLanguageLabel = computed(() => LOCALE_NAMES[locale.value] || '简体中文')
const languageOptions = SUPPORTED_LOCALES.map((code) => ({ title: LOCALE_NAMES[code], value: code }))

const mockWeekDays = ['一', '二', '三', '四', '五', '六', '日']

function changeLanguage(code) {
  setLocale(code)
}

function scrollToId(selector) {
  document.querySelector(selector)?.scrollIntoView({ behavior: 'smooth' })
}
</script>

<style scoped>
.landing-page {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 5%, rgba(76, 111, 255, 0.12), transparent 30%),
    radial-gradient(circle at 88% 22%, rgba(115, 72, 232, 0.10), transparent 30%),
    radial-gradient(circle at 50% 100%, rgba(38, 166, 154, 0.06), transparent 35%),
    #f7f8fc;
  color: #1e2942;
  font-family: Inter, 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}

/* ---------- 顶部导航 ---------- */
.landing-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  border-bottom: 1px solid rgba(20, 34, 66, 0.08);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(18px);
}

.landing-nav-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: #17233d;
  text-align: left;
  padding: 4px 8px;
  text-decoration: none;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, #3265f5, #7348e8);
  color: white;
  font-size: 13px;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(50, 101, 245, 0.24);
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.08;
}

.brand-copy strong { font-size: 17px; }
.brand-copy small { margin-top: 4px; color: #8790a5; font-size: 10px; }

.nav-actions { display: flex; align-items: center; gap: 8px; }
.nav-register { box-shadow: 0 6px 16px rgba(21, 101, 192, 0.22); }

/* ---------- Hero ---------- */
.hero {
  padding: 72px 24px 40px;
}

.hero-inner {
  max-width: 1120px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 56px;
  align-items: center;
}

.hero-chip { margin-bottom: 20px; }

.hero-title {
  font-size: clamp(34px, 4.6vw, 52px);
  line-height: 1.22;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 20px;
}

.gradient-text {
  background: linear-gradient(120deg, #3265f5, #7348e8 65%, #26a69a);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-sub {
  font-size: 17px;
  line-height: 1.75;
  color: #5a6478;
  max-width: 480px;
  margin-bottom: 30px;
}

.hero-actions {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 30px;
}

.hero-cta {
  box-shadow: 0 12px 28px rgba(21, 101, 192, 0.28);
}

.hero-points {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 22px;
}

.hero-point {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  color: #4a5568;
}

/* ---------- 产品预览卡片 ---------- */
.hero-visual {
  position: relative;
}

.hero-visual-glow {
  position: absolute;
  inset: 12% 6% -6% 6%;
  z-index: 0;
  background: linear-gradient(135deg, rgba(50, 101, 245, 0.28), rgba(115, 72, 232, 0.24));
  filter: blur(38px);
  border-radius: 32px;
}

.mock-window {
  position: relative;
  z-index: 1;
  background: #ffffff;
  border: 1px solid rgba(20, 34, 66, 0.08);
  border-radius: 20px;
  box-shadow: 0 30px 60px rgba(30, 41, 66, 0.16);
  padding: 18px;
}

.mock-window-bar {
  display: flex;
  align-items: center;
  gap: 7px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(20, 34, 66, 0.06);
  margin-bottom: 14px;
}

.mock-dot { width: 10px; height: 10px; border-radius: 50%; }
.mock-dot.red { background: #ff5f57; }
.mock-dot.yellow { background: #febc2e; }
.mock-dot.green { background: #28c840; }

.mock-window-title {
  margin-left: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: #8790a5;
}

/* 月历网格 */
.mock-month {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  margin-bottom: 12px;
}

.mock-weekday {
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  color: #8b95a8;
  padding: 4px 0;
}

.mock-day-cell {
  position: relative;
  aspect-ratio: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3px 2px;
  border-radius: 8px;
  background: #f4f6fb;
  gap: 2px;
}

.mock-day-cell.mock-today {
  background: linear-gradient(135deg, #3265f5, #7348e8);
  box-shadow: 0 4px 12px rgba(50, 101, 245, 0.25);
}

.mock-today .mock-day-num {
  color: #fff;
  font-weight: 700;
}

.mock-day-num {
  font-size: 12px;
  font-weight: 600;
  color: #3c4a66;
  line-height: 1;
}

/* 日历任务标记条 */
.mock-pill {
  width: 80%;
  height: 4px;
  border-radius: 2px;
  display: block;
  flex-shrink: 0;
}

.mock-pill-blue { background: #3265F5; }
.mock-pill-teal { background: #26A69A; }
.mock-pill-deadline { background: #FF7043; }

/* 图例 */
.mock-legend {
  display: flex;
  gap: 14px;
  padding: 8px 0 0;
  border-top: 1px solid rgba(20, 34, 66, 0.06);
  font-size: 11px;
  color: #8790a5;
}

.mock-legend i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: -1px;
}

.l-todo { background: #3265F5; }
.l-process { background: #26A69A; }
.l-deadline { background: #FF7043; }

/* 浮动 AI 对话气泡 */
.mock-chat-bubble {
  position: absolute;
  z-index: 2;
  right: -20px;
  bottom: -16px;
  width: 200px;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 14px 38px rgba(30, 41, 66, 0.2);
  border: 1px solid rgba(20, 34, 66, 0.07);
  overflow: hidden;
  animation: mockFloat 3s ease-in-out infinite;
}

@keyframes mockFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

.mock-chat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f2f6;
  font-size: 12px;
  font-weight: 600;
  color: #28334b;
}

.mock-chat-body {
  padding: 12px;
  font-size: 12px;
  color: #5a6478;
  line-height: 1.55;
}

.mock-chat-body p { margin: 0; }

.mock-chat-input {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-top: 1px solid #f0f2f6;
  background: #f8f9fc;
  font-size: 11px;
  color: #a0a7b5;
}

/* ---------- 通用区块 ---------- */
.section { padding: 72px 24px; }
.section-alt { background: rgba(255, 255, 255, 0.55); }

.section-inner {
  max-width: 1120px;
  margin: 0 auto;
}

.section-head { text-align: center; margin-bottom: 44px; }

.section-title {
  font-size: clamp(26px, 3.2vw, 36px);
  font-weight: 800;
  letter-spacing: -0.01em;
  margin-bottom: 10px;
}

.section-sub { color: #5a6478; font-size: 15.5px; }

/* ---------- 功能卡片 ---------- */
.feature-card {
  height: 100%;
  padding: 26px 24px;
  border: 1px solid rgba(20, 34, 66, 0.06);
  transition: transform 0.22s ease, box-shadow 0.22s ease;
}

.feature-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 18px 40px rgba(30, 41, 66, 0.12) !important;
}

.feature-icon {
  width: 52px;
  height: 52px;
  border-radius: 15px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 18px;
}

.icon-blue { background: rgba(50, 101, 245, 0.12); }
.icon-purple { background: rgba(115, 72, 232, 0.12); }
.icon-teal { background: rgba(38, 166, 154, 0.12); }
.icon-orange { background: rgba(255, 112, 67, 0.12); }
.icon-pink { background: rgba(233, 30, 99, 0.12); }
.icon-cyan { background: rgba(0, 188, 212, 0.12); }

.feature-card h3 {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 10px;
}

.feature-card p {
  font-size: 13.8px;
  line-height: 1.75;
  color: #5a6478;
}

/* ---------- 使用流程 ---------- */
.how-grid .v-col { display: flex; }

.how-step {
  flex: 1;
  position: relative;
  text-align: center;
  padding: 34px 26px;
  background: #fff;
  border: 1px solid rgba(20, 34, 66, 0.06);
  border-radius: 20px;
}

.how-step-num {
  position: absolute;
  top: 14px;
  right: 18px;
  font-size: 30px;
  font-weight: 800;
  color: rgba(20, 34, 66, 0.07);
  line-height: 1;
}

.how-icon {
  width: 60px;
  height: 60px;
  margin: 0 auto 18px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #3265f5, #7348e8);
  box-shadow: 0 12px 26px rgba(50, 101, 245, 0.3);
}

.how-step h3 { font-size: 17px; font-weight: 700; margin-bottom: 10px; }
.how-step p {
  font-size: 13.8px;
  line-height: 1.75;
  color: #5a6478;
  margin: 0 auto;
  max-width: 260px;
}

/* ---------- CTA ---------- */
.cta-card {
  overflow: hidden;
  background:
    radial-gradient(circle at 85% 20%, rgba(255, 255, 255, 0.18), transparent 40%),
    linear-gradient(120deg, #3265f5, #5a4bd1 55%, #7348e8);
  box-shadow: 0 24px 50px rgba(50, 101, 245, 0.32);
}

.cta-inner {
  padding: 60px 24px;
  text-align: center;
  color: #fff;
}

.cta-inner h2 {
  font-size: clamp(24px, 3vw, 32px);
  font-weight: 800;
  margin-bottom: 12px;
}

.cta-inner p {
  font-size: 15.5px;
  opacity: 0.88;
  margin-bottom: 28px;
}

.cta-btn {
  color: #3265f5 !important;
  font-weight: 800;
  box-shadow: 0 12px 26px rgba(20, 30, 66, 0.28);
}

/* ---------- Footer ---------- */
.landing-footer {
  border-top: 1px solid rgba(20, 34, 66, 0.06);
  padding: 30px 24px;
  background: rgba(255, 255, 255, 0.6);
}

.landing-footer-inner {
  max-width: 1120px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
}

.landing-footer-inner p {
  font-size: 12.5px;
  color: #8790a5;
}

/* ---------- 响应式 ---------- */
@media (max-width: 900px) {
  .hero { padding: 48px 20px 24px; }
  .hero-inner { grid-template-columns: 1fr; gap: 44px; }
  .hero-visual { max-width: 460px; margin: 0 auto; }
}

@media (max-width: 600px) {
  .landing-nav-inner { padding: 10px 14px; }
  .brand-copy small { display: none; }
  .section { padding: 52px 18px; }
  .hero-actions .v-btn { width: 100%; }
  .nav-actions .v-btn--size-large { padding: 0 10px; }
  .landing-footer-inner { justify-content: center; text-align: center; }
}
</style>
