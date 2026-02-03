// BOSS Scraper Bridge - Content Script
console.log("🚀 BOSS Scraper Bridge: 脚本已加载");

// 1. 基础工具函数
function getPageType() {
    const url = window.location.href;
    if (url.includes('/job_detail/')) return 'detail';
    if (url.includes('/geek/jobs')) return 'list';
    return 'unknown';
}

function updateStatus(text, color) {
    const status = document.getElementById('scrape-status');
    if (status) {
        status.innerText = text;
        if (color) status.style.color = color;
    }
}

// 2. UI 创建逻辑 (改为非阻塞式)
function createUI() {
    if (document.getElementById('boss-scraper-panel')) return;

    const pageType = getPageType();
    const div = document.createElement('div');
    div.id = 'boss-scraper-panel';
    div.innerHTML = `
        <div style="position: fixed; top: 20px; right: 20px; z-index: 999999; background: white; border: 1px solid #ccc; padding: 15px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); font-family: sans-serif; min-width: 160px;">
            <h4 style="margin: 0 0 12px 0; font-size: 16px; color: #333; border-bottom: 1px solid #eee; padding-bottom: 8px;">BOSS 采集桥</h4>
            
            <button id="btn-scrape-list" style="display: ${pageType === 'list' ? 'block' : 'none'}; width: 100%; margin-bottom: 8px; padding: 10px; background: #00d7c6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">抓取本页列表</button>
            <button id="btn-scrape-detail" style="display: ${pageType === 'detail' ? 'block' : 'none'}; width: 100%; margin-bottom: 8px; padding: 10px; background: #409eff; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">抓取当前详情</button>
            <button id="btn-auto-pilot" style="display: block; width: 100%; padding: 10px; background: #4caf50; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">开启自动巡航</button>
            
            <div style="margin-top: 10px; font-size: 12px; color: #999;">
                页面类型: <span style="color: #666;">${pageType === 'list' ? '搜索列表' : (pageType === 'detail' ? '职位详情' : '其他')}</span>
            </div>
            <div id="scrape-status" style="margin-top: 8px; font-size: 12px; color: #ff9900; font-weight: bold;">等待操作...</div>
        </div>
    `;
    document.body.appendChild(div);

    // 绑定事件
    const btnList = document.getElementById('btn-scrape-list');
    if (btnList) btnList.addEventListener('click', () => {
        console.log("🖱️ 点击了抓取列表");
        scrapeList();
    });

    const btnDetail = document.getElementById('btn-scrape-detail');
    if (btnDetail) btnDetail.addEventListener('click', () => {
        console.log("🖱️ 点击了抓取详情");
        scrapeDetail();
    });

    const btnAuto = document.getElementById('btn-auto-pilot');
    if (btnAuto) btnAuto.addEventListener('click', () => {
        console.log("🖱️ 点击了自动巡航");
        toggleAutoPilot();
    });

    // 检查是否应该继续巡航
    chrome.storage.local.get(['isAutoPilot'], (res) => {
        if (res.isAutoPilot) {
            btnAuto.innerText = "停止巡航";
            btnAuto.style.background = "#f56c6c";
            updateStatus("🚀 巡航模式运行中...", "#f56c6c");
            setTimeout(runAutoPilot, 3000);
        }
    });
}

// 3. 抓取逻辑
async function scrapeList() {
    updateStatus("正在寻找卡片...");
    const selectors = ['.job-card-wrapper', '.job-list-box li', '.rec-job-list li', '.job-card-body'];
    let jobCards = [];
    for (const sel of selectors) {
        const found = document.querySelectorAll(sel);
        if (found.length > 0) { jobCards = Array.from(found); break; }
    }

    if (jobCards.length === 0) {
        updateStatus("❌ 未找到职位", "red");
        return;
    }

    const jobs = [];
    jobCards.forEach(card => {
        const titleEl = card.querySelector('a.job-name') || card.querySelector('.job-title') || card.querySelector('a');
        const companyEl = card.querySelector('.company-name a') || card.querySelector('.company-text a') || card.querySelector('.company-name');
        const salaryEl = card.querySelector('.salary');
        const cityEl = card.querySelector('.job-area') || card.querySelector('.job-area-wrapper');
        
        if (titleEl && titleEl.href) {
            jobs.push({
                title: titleEl.innerText.trim(),
                source_url: titleEl.href.split('?')[0],
                team: companyEl ? companyEl.innerText.trim().replace('公司名称', '').trim() : "",
                salary: salaryEl ? salaryEl.innerText.trim() : "",
                city: cityEl ? cityEl.innerText.trim() : "",
                source_name: "BOSS直聘", 
                type: "国内",
                is_remote: "1"
            });
        }
    });

    updateStatus(`同步中(${jobs.length})...`);
    const res = await sendToServer('/upload_list', { jobs });
    updateStatus(res.success ? `✅ 成功同步 ${jobs.length} 条` : "❌ 连不上 Python");
}

async function scrapeDetail() {
    updateStatus("解析详情中...");
    try {
        const detail = {
            source_url: window.location.href.split('?')[0],
            title: document.querySelector('.job-banner h1')?.innerText.trim() || document.querySelector('h1')?.innerText.trim() || "",
            description: Array.from(document.querySelectorAll('.job-sec-text')).map(n => n.innerText.trim()).join('\n'),
            keywords: Array.from(document.querySelectorAll('.job-keyword-list li')).map(n => n.innerText.trim()),
            salary: document.querySelector('.job-banner .salary')?.innerText.trim() || document.querySelector('.salary')?.innerText.trim() || "",
            experience: document.querySelector('.text-desc.text-experience')?.innerText.trim() || 
                        document.querySelector('.text-desc.text-experiece')?.innerText.trim() || 
                        document.querySelector('.job-banner .text-desc:nth-child(2)')?.innerText.trim() || "",
            city: document.querySelector('.text-desc.text-city')?.innerText.trim() || 
                  document.querySelector('.text-city')?.innerText.trim() || 
                  document.querySelector('.job-banner .text-desc:nth-child(1)')?.innerText.trim() || "",
            team: document.querySelector('.level-list .company-name')?.innerText.trim()?.replace('公司名称', '').trim() || "",
            status: document.querySelector('.job-status')?.innerText.trim() || "在招",
            createdAt: ""
        };

        // --- 特殊逻辑：识别代招公司 ---
        if (!detail.team || detail.team === "") {
            const pageText = document.body.innerText;
            const daiZhaoMatch = pageText.match(/代招公司[:：\s]+([^\n\s!！？,，。]+)/);
            if (daiZhaoMatch && daiZhaoMatch[1]) {
                detail.team = daiZhaoMatch[1].trim();
                console.log("🔍 发现代招公司:", detail.team);
            }
        }

        // 提取发布时间 (严格同步 boss_deprecated 逻辑)
        try {
            const metaNode = document.querySelector("meta[property='bytedance:updated_time']");
            if (metaNode && metaNode.content) {
                detail.createdAt = metaNode.content.strip ? metaNode.content.strip().split('T')[0] : metaNode.content.split('T')[0];
            } else {
                const createdAtNode = document.querySelector('.bytedance\\:updated_time');
                if (createdAtNode && createdAtNode.innerText) {
                    detail.createdAt = createdAtNode.innerText.trim().split('T')[0];
                }
            }
        } catch (e) {
            console.warn("提取时间失败:", e);
        }

        const res = await sendToServer('/upload_detail', detail);
        updateStatus(res.success ? "✅ 详情已同步" : "❌ 连不上 Python");
        return res;
    } catch (e) {
        updateStatus("❌ 解析异常", "red");
        console.error("解析详情失败:", e);
        return { success: false };
    }
}

// 4. 巡航逻辑
async function toggleAutoPilot() {
    chrome.storage.local.get(['isAutoPilot'], async (res) => {
        const newState = !res.isAutoPilot;
        await chrome.storage.local.set({ isAutoPilot: newState });
        window.location.reload(); // 刷新页面以应用新状态
    });
}

async function runAutoPilot() {
    const pageType = getPageType();
    if (pageType === 'detail') {
        const res = await scrapeDetail();
        if (!res.success) return;
        const wait = 4000 + Math.random() * 4000;
        updateStatus(`⏱️ ${ (wait/1000).toFixed(1) }s 后跳下一个...`);
        await new Promise(r => setTimeout(r, wait));
    }
    updateStatus("🔍 索要任务...");
    const task = await sendToServer('/get_next_url', {});
    if (task.success && task.url) {
        window.location.href = task.url;
    } else {
        updateStatus("🏁 任务已全部完成！");
        chrome.storage.local.set({ isAutoPilot: false });
    }
}

async function sendToServer(endpoint, data) {
    const server_url = `http://127.0.0.1:5000${endpoint}`;
    
    return new Promise((resolve) => {
        chrome.runtime.sendMessage({
            type: 'FETCH',
            data: {
                url: server_url,
                options: {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                }
            }
        }, (response) => {
            if (chrome.runtime.lastError) {
                console.error("❌ 插件内部通信失败:", chrome.runtime.lastError.message);
                updateStatus("❌ 插件异常，请刷新插件页面", "red");
                resolve({ success: false });
                return;
            }

            if (response && response.success) {
                console.log("✅ 通信成功:", response.data);
                resolve({ ...response.data, success: true });
            } else {
                console.error("❌ 无法连接到 Python 服务器:", response?.error || "未知错误");
                updateStatus("❌ 连不上后端，请检查终端", "red");
                resolve({ success: false });
            }
        });
    });
}

// 启动
setTimeout(createUI, 2000);
let lastUrl = window.location.href;
setInterval(() => {
    if (window.location.href !== lastUrl) {
        lastUrl = window.location.href;
        const p = document.getElementById('boss-scraper-panel');
        if (p) p.remove();
        createUI();
    }
}, 2000);
