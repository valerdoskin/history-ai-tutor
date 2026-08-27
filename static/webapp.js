// History AI Tutor — Web App логика

const tg = window.Telegram?.WebApp;
let userId = null;

// Инициализация Telegram Web App
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#1a1a2e');
    tg.setBackgroundColor('#1a1a2e');
    userId = tg.initDataUnsafe?.user?.id || null;
}

// ============================================================
// Вкладки
// ============================================================
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        if (tab.dataset.tab === 'profile') loadProfile();
    });
});

// ============================================================
// Чат
// ============================================================
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

function addMessage(text, isUser) {
    const div = document.createElement('div');
    div.className = `message ${isUser ? 'user' : 'bot'}`;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    div.appendChild(bubble);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    addMessage(text, true);
    chatInput.value = '';

    // Показываем индикатор печати
    const typing = document.createElement('div');
    typing.className = 'message bot';
    typing.innerHTML = '<div class="bubble typing">...</div>';
    chatMessages.appendChild(typing);

    try {
        const resp = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: text, user_id: userId }),
        });
        const data = await resp.json();
        typing.remove();
        addMessage(data.answer || 'Извини, не удалось получить ответ.', false);
    } catch (e) {
        typing.remove();
        addMessage('Ошибка соединения. Попробуй ещё раз.', false);
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// ============================================================
// Практика
// ============================================================
const practiceBtn = document.getElementById('practice-btn');
const practiceContent = document.getElementById('practice-content');

practiceBtn.addEventListener('click', async () => {
    const examType = document.getElementById('exam-type').value;
    practiceContent.innerHTML = '<p class="hint">Генерация задания...</p>';
    try {
        const resp = await fetch(`/api/exam?type=${examType}&user_id=${userId}`);
        const data = await resp.json();
        renderQuestion(data);
    } catch (e) {
        practiceContent.innerHTML = '<p class="hint">Ошибка генерации задания.</p>';
    }
});

function renderQuestion(data) {
    if (data.options) {
        // ОГЭ — выбор ответа
        let html = `<div class="question">${data.question}</div><div class="options">`;
        data.options.forEach((opt, i) => {
            html += `<button class="option" data-idx="${i}" data-correct="${i === data.correct_index}">${i + 1}. ${opt}</button>`;
        });
        html += '</div><div class="explanation" id="explanation"></div>';
        practiceContent.innerHTML = html;

        document.querySelectorAll('.option').forEach(btn => {
            btn.addEventListener('click', () => {
                const correct = btn.dataset.correct === 'true';
                document.querySelectorAll('.option').forEach(b => b.disabled = true);
                if (correct) {
                    btn.classList.add('correct');
                } else {
                    btn.classList.add('wrong');
                    document.querySelector(`.option[data-correct="true"]`).classList.add('correct');
                }
                document.getElementById('explanation').textContent = data.explanation || '';
            });
        });
    } else {
        // ЕГЭ — краткий ответ
        practiceContent.innerHTML = `
            <div class="question">${data.question}</div>
            <input type="text" id="ege-answer" placeholder="Введи ответ...">
            <button class="btn-primary" id="ege-check">Проверить</button>
            <div class="explanation" id="explanation"></div>
        `;
        document.getElementById('ege-check').addEventListener('click', () => {
            const answer = document.getElementById('ege-answer').value.trim();
            const correct = answer.toLowerCase() === (data.answer || '').toLowerCase();
            const expl = document.getElementById('explanation');
            if (correct) {
                expl.textContent = '✅ Верно! ' + (data.explanation || '');
                expl.className = 'explanation correct';
            } else {
                expl.textContent = '❌ Неверно. Правильный ответ: ' + data.answer + '. ' + (data.explanation || '');
                expl.className = 'explanation wrong';
            }
        });
    }
}

// ============================================================
// Профиль
// ============================================================
async function loadProfile() {
    const content = document.getElementById('profile-content');
    try {
        const resp = await fetch(`/api/profile?user_id=${userId}`);
        const data = await resp.json();
        const user = data.user || {};
        const stats = data.stats || {};
        content.innerHTML = `
            <div class="profile-card">
                <div class="profile-name">${user.first_name || 'Ученик'}</div>
                <div class="profile-rank">${data.rank || 'Новичок'}</div>
                <div class="profile-stats">
                    <div class="stat"><span class="stat-value">${user.level || 1}</span><span class="stat-label">Уровень</span></div>
                    <div class="stat"><span class="stat-value">${user.xp || 0}</span><span class="stat-label">XP</span></div>
                    <div class="stat"><span class="stat-value">${user.streak || 0}🔥</span><span class="stat-label">Серия</span></div>
                    <div class="stat"><span class="stat-value">${stats.accuracy || 0}%</span><span class="stat-label">Точность</span></div>
                </div>
                <div class="achievements">
                    <h3>🏆 Достижения</h3>
                    ${data.achievements?.length ? data.achievements.map(a => `<div class="achievement">${a.title}</div>`).join('') : '<p class="hint">Пока нет достижений</p>'}
                </div>
            </div>
        `;
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка загрузки профиля.</p>';
    }
}
