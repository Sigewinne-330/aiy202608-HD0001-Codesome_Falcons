<template>
  <div class="landing-page">
    <!-- ================= 顶部导航 ================= -->
    <header class="landing-nav">
      <div class="landing-nav-inner">
        <router-link to="/" class="brand-button" aria-label="返回首页">
          <span class="brand-mark">IB</span>
          <span class="brand-copy">
            <strong>IBuddy</strong>
            <small>长期任务规划师</small>
          </span>
        </router-link>

        <div class="nav-actions">
          <v-btn variant="text" color="primary" rounded="lg" to="/login">登录</v-btn>
          <v-btn color="primary" rounded="lg" to="/register" class="nav-register">免费开始</v-btn>
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
              专为 IB 学子打造
            </v-chip>

            <h1 class="hero-title">
              别再被 DDL 追着跑，<br />
              <span class="gradient-text">让 AI 帮你提前规划</span>
            </h1>

            <p class="hero-sub">
              全模态录入 · AI 逆向拆解 · 智能排期
              —— 把每一项 Deadline 变成有条不紊的推进计划。
            </p>

            <div class="hero-actions">
              <v-btn
                size="x-large"
                color="primary"
                rounded="lg"
                to="/register"
                class="hero-cta"
                elevation="4"
              >
                立即开始
                <v-icon end>mdi-arrow-right</v-icon>
              </v-btn>
              <v-btn
                size="x-large"
                variant="outlined"
                color="primary"
                rounded="lg"
                @click="scrollToId('#features')"
              >
                了解功能
              </v-btn>
            </div>

            <div class="hero-points">
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>语音 / 图片 / 文本全模态录入</span>
              </div>
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>从 DDL 倒推子任务</span>
              </div>
              <div class="hero-point">
                <v-icon color="success" size="18">mdi-check-circle</v-icon>
                <span>自动避让冲突日期</span>
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
                <span class="mock-window-title">8 月 · 日历工作台</span>
              </div>

              <div class="mock-week">
                <div class="mock-day"><small>一</small><b>3</b></div>
                <div class="mock-day"><small>二</small><b>4</b></div>
                <div class="mock-day is-today"><small>三</small><b>5</b></div>
                <div class="mock-day"><small>四</small><b>6</b></div>
                <div class="mock-day"><small>五</small><b>7</b></div>
                <div class="mock-day"><small>六</small><b>8</b></div>
                <div class="mock-day"><small>日</small><b>9</b></div>
              </div>

              <div class="mock-task mock-task-blue">
                <v-icon size="15" color="white">mdi-file-document-edit-outline</v-icon>
                <div class="mock-task-copy">
                  <b>EE 论文 · 初稿</b>
                  <small>8月20日 截止</small>
                </div>
                <span class="mock-task-state">拆解中</span>
              </div>

              <div class="mock-task mock-task-orange">
                <v-icon size="15" color="white">mdi-book-open-variant</v-icon>
                <div class="mock-task-copy">
                  <b>历史 IA 实验</b>
                  <small>8月12日 截止</small>
                </div>
                <span class="mock-task-state">催办中</span>
              </div>

              <div class="mock-task mock-task-teal">
                <v-icon size="15" color="white">mdi-flask-outline</v-icon>
                <div class="mock-task-copy">
                  <b>化学 Lab Report</b>
                  <small>8月15日 截止</small>
                </div>
                <span class="mock-task-state">已排期</span>
              </div>

              <div class="mock-bubble">
                <v-icon size="15" color="#FF7043">mdi-bell-ring-outline</v-icon>
                <span>3 天后 · 历史 IA 到期，该动工啦～</span>
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
              核心功能
            </v-chip>
            <h2 class="section-title">四大模块，一站式管住所有 DDL</h2>
            <p class="section-sub">从录入、拆解到排期与督促，AI 全程陪伴你的长程任务</p>
          </div>

          <v-row class="feature-grid" dense>
            <v-col cols="12" sm="6" lg="3">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-blue">
                  <v-icon size="26" color="#3265F5">mdi-creation-outline</v-icon>
                </div>
                <h3>全模态 DDL 捕获网</h3>
                <p>文本、语音、图片三种方式录入任务，Agent 自动识别任务、时间与地点，日历实时生成，再也不翻聊天记录。</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="3">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-purple">
                  <v-icon size="26" color="#7348E8">mdi-sitemap-outline</v-icon>
                </div>
                <h3>双核长程拆解引擎</h3>
                <p>从截止日期倒推生成多节点子任务，内置 IB 学科专家知识库，按官方指南给出专业级周度拆解。</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="3">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-teal">
                  <v-icon size="26" color="#26A69A">mdi-lightning-bolt-outline</v-icon>
                </div>
                <h3>动态精力池管理</h3>
                <p>AI 读取已有日程智能避让冲突，任务见缝插针排进空闲区；遇到「地狱周」一键平滑化，把压力打散前置。</p>
              </v-card>
            </v-col>

            <v-col cols="12" sm="6" lg="3">
              <v-card class="feature-card" rounded="xl" elevation="1">
                <div class="feature-icon icon-orange">
                  <v-icon size="26" color="#FF7043">mdi-robot-happy-outline</v-icon>
                </div>
                <h3>有温度的督导员</h3>
                <p>戏精幽默的催收文案，在 Deadline 临近时用有趣的方式提醒你——催得动、不焦虑，保持学习动力。</p>
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
              三步上手
            </v-chip>
            <h2 class="section-title">就像发消息一样简单</h2>
            <p class="section-sub">把大脑里的任务倒给 Agent，剩下的交给它</p>
          </div>

          <v-row class="how-grid">
            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">01</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-message-text-outline</v-icon>
                </div>
                <h3>说 / 拍 / 贴</h3>
                <p>把任务、聊天截图或课件丢给 Agent，一句话、一张图就能完成录入。</p>
              </div>
            </v-col>

            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">02</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-calendar-clock-outline</v-icon>
                </div>
                <h3>AI 拆解排期</h3>
                <p>从 DDL 倒推子任务并落到日历，自动避开已经排满的日期。</p>
              </div>
            </v-col>

            <v-col cols="12" md="4">
              <div class="how-step">
                <div class="how-step-num">03</div>
                <div class="how-icon">
                  <v-icon size="30" color="white">mdi-bell-ring-outline</v-icon>
                </div>
                <h3>节奏推进</h3>
                <p>日历实时同步进度，到期前收到幽默提醒，每一步都心里有数。</p>
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
              <h2>准备好告别手忙脚乱了吗？</h2>
              <p>免费开始使用，3 分钟上手，让每一个 Deadline 都从容落地。</p>
              <v-btn
                size="x-large"
                color="white"
                rounded="lg"
                class="cta-btn"
                to="/register"
              >
                <v-icon start>mdi-rocket-launch</v-icon>
                立即注册，免费体验
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
            <small>长期任务规划师</small>
          </span>
        </div>
        <p>© 2026 IBuddy · 用 AI 让每一个 DDL 都从容落地</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
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

.mock-week {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
  margin-bottom: 14px;
}

.mock-day {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 0;
  border-radius: 12px;
  background: #f4f6fb;
  font-size: 12px;
  color: #5a6478;
}

.mock-day b { font-size: 15px; color: #1e2942; }
.mock-day.is-today {
  background: linear-gradient(135deg, #3265f5, #7348e8);
  box-shadow: 0 8px 18px rgba(50, 101, 245, 0.3);
}
.mock-day.is-today small,
.mock-day.is-today b { color: #fff; }

.mock-task {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  border-radius: 13px;
  margin-bottom: 10px;
  color: #fff;
}

.mock-task-blue { background: linear-gradient(135deg, #3265f5, #4d7dff); }
.mock-task-orange { background: linear-gradient(135deg, #ff7043, #ff9a5a); }
.mock-task-teal { background: linear-gradient(135deg, #26a69a, #4ecdc4); }

.mock-task-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.mock-task-copy b { font-size: 13.5px; }
.mock-task-copy small { font-size: 11px; opacity: 0.82; }

.mock-task-state {
  font-size: 10.5px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.22);
  white-space: nowrap;
}

.mock-bubble {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 11px 13px;
  border: 1px solid rgba(255, 112, 67, 0.24);
  background: #fff7f3;
  border-radius: 13px;
  font-size: 12.5px;
  font-weight: 600;
  color: #b4552a;
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
