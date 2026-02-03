// 智联招聘采集桥 - Content Script
console.log("🚀 智联招聘采集桥: 脚本已加载");

// 1. 基础工具函数
function getPageType() {
    const url = window.location.href;
    if (url.includes('jobdetail/') || url.includes('jobs.zhaopin.com')) return 'detail';
    if (url.includes('/sou/') || url.includes('sou.zhaopin.com')) return 'list';
    return 'unknown';
}

function updateStatus(text, color) {
    const status = document.getElementById('scrape-status');
    if (status) {
        status.innerText = text;
        if (color) status.style.color = color;
    }
}

// 2. UI 创建逻辑
function createUI() {
    if (document.getElementById('zhilian-scraper-panel')) return;

    const pageType = getPageType();
    const div = document.createElement('div');
    div.id = 'zhilian-scraper-panel';
    div.innerHTML = `
        <div style="position: fixed; top: 20px; right: 20px; z-index: 999999; background: white; border: 1px solid #ccc; padding: 15px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); font-family: sans-serif; min-width: 160px;">
            <h4 style="margin: 0 0 12px 0; font-size: 16px; color: #333; border-bottom: 1px solid #eee; padding-bottom: 8px;">智联采集桥</h4>
            
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
    chrome.storage.local.get(['isAutoPilot_zhilian'], (res) => {
        if (res.isAutoPilot_zhilian) {
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
    // 智联常见的列表项选择器
    const selectors = [
        '.positionlist .jobinfo', // 用户提供的结构
        '.joblist-box__item', 
        '.positionlist__item', 
        '.job-card', 
        '.job-list-item', 
        '.item-list-box'
    ];
    let jobCards = [];
    for (const sel of selectors) {
        const found = document.querySelectorAll(sel);
        if (found.length > 0) { jobCards = Array.from(found); break; }
    }

    if (jobCards.length === 0) {
        // 兜底尝试寻找包含 job-name 或类似词汇的 a 标签的父级
        const possibleLinks = document.querySelectorAll('a[class*="name"], a[class*="title"]');
        if (possibleLinks.length > 0) {
            jobCards = Array.from(new Set(Array.from(possibleLinks).map(a => a.closest('div') || a.parentElement)));
        }
    }

    if (jobCards.length === 0) {
        updateStatus("❌ 未找到职位", "red");
        return;
    }

    const jobs = [];
    jobCards.forEach(card => {
        // 尝试多种可能的子选择器
        // 优先尝试用户提供的结构: .jobinfo_top a
        const titleEl = card.querySelector('.jobinfo_top a') || 
                        card.querySelector('.joblist-box__item-name') || 
                        card.querySelector('.position-name') || 
                        card.querySelector('a[class*="name"]') || 
                        card.querySelector('a');
        
        const companyEl = card.querySelector('.company-name') || 
                          card.querySelector('.company-text a') || 
                          card.querySelector('.company__name') ||
                          card.querySelector('.companyinfo a');
        
        const salaryEl = card.querySelector('.joblist-box__item-salary') || 
                         card.querySelector('.job-salary') || 
                         card.querySelector('.item-salary') ||
                         card.querySelector('.jobinfo_top_salary');
        
        const cityEl = card.querySelector('.joblist-box__item-address') || 
                       card.querySelector('.job-address') || 
                       card.querySelector('.item-address') ||
                       card.querySelector('.jobinfo_top_city');
        
        const linkEl = titleEl?.tagName === 'A' ? titleEl : (titleEl?.querySelector('a') || card.querySelector('a'));

        if (titleEl && linkEl && linkEl.href) {
            jobs.push({
                title: titleEl.innerText.trim(),
                source_url: linkEl.href.split('?')[0],
                team: companyEl ? companyEl.innerText.trim() : "",
                salary: salaryEl ? salaryEl.innerText.trim() : "",
                city: cityEl ? cityEl.innerText.trim() : "",
                source_name: "智联招聘", 
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
        const infoLis = document.querySelectorAll('.summary-plane__info li');
        let city = "";
        let experience = "经验不限"; // 默认值
        let foundExp = false;
        
        infoLis.forEach((li, index) => {
            const text = li.innerText.trim();
            
            // 提取地区：通常是第一个带有 a 标签的 li
            if (index === 0) {
                const cityAnchor = li.querySelector('a');
                city = cityAnchor ? cityAnchor.innerText.trim() : text;
            }
            
            // 提取经验：遍历所有 li，寻找包含“经验”、“年”或“不限”的文字
            if (!foundExp && (
                text.includes('经验') || 
                text.includes('不限') || 
                /\d+-\d+年/.test(text) || 
                /\d+年以/.test(text)
            )) {
                experience = text;
                foundExp = true;
            }
        });

        const detail = {
            source_url: window.location.href.split('?')[0],
            title: document.querySelector('.summary-plane__title')?.innerText.trim() || document.querySelector('.job-summary__title')?.innerText.trim() || document.querySelector('h1')?.innerText.trim() || "",
            description: document.querySelector('.describtion__detail-content')?.innerText.trim() || document.querySelector('.job-detail')?.innerText.trim() || "",
            keywords: Array.from(document.querySelectorAll('.describtion__skills-item')).map(n => n.innerText.trim()),
            salary: document.querySelector('.summary-plane__salary')?.innerText.trim() || document.querySelector('.job-summary__salary')?.innerText.trim() || "",
            experience: experience || document.querySelector('.job-summary__exp')?.innerText.trim() || "",
            city: city || document.querySelector('.job-summary__city')?.innerText.trim() || "",
            team: document.querySelector('.company__title')?.innerText.trim() || document.querySelector('.company-name')?.innerText.trim() || document.querySelector('.company__name')?.innerText.trim() || "",
            status: "在招",
            createdAt: new Date().toISOString().split('T')[0]
        };

        // 兜底关键词提取
        if (detail.keywords.length === 0) {
            detail.keywords = Array.from(document.querySelectorAll('.job-summary__tags span, .job-keyword-list li')).map(n => n.innerText.trim());
        }

        // 尝试寻找发布时间 (增强版)
        try {
            const timeEl = document.querySelector('.iconfont.icon-update-time')?.parentElement || 
                           document.querySelector('.update-date') || 
                           document.querySelector('.publish-time');
            if (timeEl) {
                const timeText = timeEl.innerText;
                
                if (timeText.includes('今天')) {
                    const now = new Date();
                    const year = now.getFullYear();
                    const month = (now.getMonth() + 1).toString().padStart(2, '0');
                    const day = now.getDate().toString().padStart(2, '0');
                    detail.createdAt = `${year}-${month}-${day}`;
                } else {
                    // 匹配 "x月x日"
                    const dateMatch = timeText.match(/(\d+)月(\d+)日/);
                    if (dateMatch) {
                        const month = parseInt(dateMatch[1]);
                        const day = parseInt(dateMatch[2]);
                        const now = new Date();
                        let year = now.getFullYear();
                        
                        // 如果提取的月份大于当前月份，说明是去年的职位 (例如现在1月，职位是11月)
                        if (month > (now.getMonth() + 1)) {
                            year -= 1;
                        }
                        
                        const monthStr = month.toString().padStart(2, '0');
                        const dayStr = day.toString().padStart(2, '0');
                        detail.createdAt = `${year}-${monthStr}-${dayStr}`;
                    } else {
                        // 兜底匹配 YYYY-MM-DD
                        const isoMatch = timeText.match(/\d{4}-\d{2}-\d{2}/);
                        if (isoMatch) detail.createdAt = isoMatch[0];
                    }
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
    chrome.storage.local.get(['isAutoPilot_zhilian'], async (res) => {
        const newState = !res.isAutoPilot_zhilian;
        await chrome.storage.local.set({ isAutoPilot_zhilian: newState });
        window.location.reload();
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
        chrome.storage.local.set({ isAutoPilot_zhilian: false });
    }
}

async function sendToServer(endpoint, data) {
    const server_url = `http://127.0.0.1:5001${endpoint}`;
    
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
        const p = document.getElementById('zhilian-scraper-panel');
        if (p) p.remove();
        createUI();
    }
}, 2000);
