// Wellfound Scraper Bridge - Content Script
console.log("🚀 Wellfound Scraper Bridge: 脚本已加载");

// 1. 基础工具函数
function getPageType() {
    const url = window.location.href;
    if (url.includes('/jobs/')) return 'detail'; // URL usually has /jobs/id-title or just /jobs sometimes check carefully
    // Wellfound job URLs are usually like https://wellfound.com/jobs/12345-title
    
    // Check elements for list view vs detail view
    if (document.querySelector('.styles_jobListingList__YGDNO')) return 'list';
    if (document.querySelector('.styles_description__36q7q')) return 'detail';
    
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
    if (document.getElementById('boss-scraper-panel')) return;

    const pageType = getPageType();
    const div = document.createElement('div');
    div.id = 'boss-scraper-panel';
    div.innerHTML = `
        <div style="position: fixed; top: 20px; right: 20px; z-index: 999999; background: white; border: 1px solid #ccc; padding: 15px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); font-family: sans-serif; min-width: 160px;">
            <h4 style="margin: 0 0 12px 0; font-size: 16px; color: #333; border-bottom: 1px solid #eee; padding-bottom: 8px;">Wellfound Bridge</h4>
            
            <button id="btn-scrape-list" style="display: block; width: 100%; margin-bottom: 8px; padding: 10px; background: #00d7c6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">抓取本页列表</button>
            <button id="btn-scrape-detail" style="display: block; width: 100%; margin-bottom: 8px; padding: 10px; background: #409eff; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">抓取当前详情</button>
            <button id="btn-auto-pilot" style="display: block; width: 100%; padding: 10px; background: #4caf50; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">开启自动巡航</button>
            
            <div style="margin-top: 10px; font-size: 12px; color: #999;">
                页面类型: <span style="color: #666;">${pageType === 'list' ? '列表' : (pageType === 'detail' ? '详情' : '未知')}</span>
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
    // 岗位页面结构为：
    // styles_component__uTjje 为 job item 的 container (Actually Company Container)
    // 里面包含了一个公司名字，和若干条这个公司在招的岗位。
    // 公司名字在：div.styles_headerContainer__GfbYF > div > a > div > div > div > a > h2
    // 在招岗位在：styles_jobListingList__YGDNO 这个类下面，有若干个 styles_component__Ey28k 类。
    // styles_component__Ey28k下面的第一个child有个href，是岗位链接。
    // styles_titleBar__f7F5e 里面有个span这个span里的text是岗位标题。
    
    // There are multiple company containers
    const companyContainers = document.querySelectorAll('.styles_component__uTjje');
    if (companyContainers.length === 0) {
        updateStatus("❌ 未找到列表", "red");
        return;
    }

    let jobs = [];
    
    companyContainers.forEach(container => {
        // Extract Company Name
        const companyNameEl = container.querySelector('.styles_headerContainer__GfbYF > div > a > div > div > div > a > h2');
        const companyName = companyNameEl ? companyNameEl.innerText.trim() : "";
        
        // Find job list container
        const jobListContainer = container.querySelector('.styles_jobListingList__YGDNO');
        if (!jobListContainer) return;
        
        // Find individual jobs
        const jobItems = jobListContainer.querySelectorAll('.styles_component__Ey28k');
        
        jobItems.forEach(item => {
            // Link is in the first child
            const firstChild = item.firstElementChild;
            const link = firstChild && firstChild.href ? firstChild.href : "";
            
            // Title
            const titleEl = item.querySelector('.styles_titleBar__f7F5e span');
            const title = titleEl ? titleEl.innerText.trim() : "";
            
            // Other details like salary/location are sometimes visible in list, but user didn't specify list selectors for them.
            // We'll rely on detail page for those, or extract if needed. 
            // We just need basic info for list upload.
            
            if (link && title) {
                jobs.push({
                    title: title,
                    source_url: link.split('?')[0],
                    team: companyName,
                    salary: "", // Optional in list
                    city: "",   // Optional in list
                    source_name: "wellfound", 
                    type: "国外",
                    is_remote: "1"
                });
            }
        });
    });

    if (jobs.length === 0) {
         updateStatus("❌ 未找到有效职位", "red");
         return;
    }

    updateStatus(`同步中(${jobs.length})...`);
    const res = await sendToServer('/upload_list', { jobs });
    updateStatus(res.success ? `✅ 成功同步 ${jobs.length} 条` : "❌ 连不上 Python");
}

async function scrapeDetail() {
    updateStatus("解析详情中...");
    try {
        // 5. 判断 全文寻找 <dt>Hires remotely </dt>
        let hiresRemotely = "";
        const allDTs = Array.from(document.querySelectorAll('dt'));
        const hiresDT = allDTs.find(dt => dt.innerText.trim().includes('Hires remotely'));
        if (hiresDT) {
            const hiresDD = hiresDT.nextElementSibling;
            if (hiresDD) {
                hiresRemotely = hiresDD.innerText.trim().toLowerCase();
            }
        }

        // 如果没有 everywhere，说明不接受中国候选人，跳过并告知后端已处理
        if (hiresRemotely && !hiresRemotely.includes('everywhere')) {
            updateStatus("⏭️ 非全球远程，已标记跳过", "#999");
            console.log("⏭️ 职位仅限特定区域远程 (" + hiresRemotely + ")，不符合全球远程要求。");
            // 告知后端此 ID 已处理且非远程，防止 get_next_url 陷入死循环
            await sendToServer('/upload_detail', { 
                source_url: window.location.href.split('?')[0],
                is_remote: "0",
                title: "Skipped (Not Global Remote)"
            });
            return { success: true, skipped: true }; 
        }

        const descriptionEl = document.querySelector('.styles_description__36q7q');
        const description = descriptionEl ? descriptionEl.innerText.trim() : "";

        // 3. Salary 换算逻辑
        const salaryEl = document.querySelector('.styles_subheader__DfKjh');
        let rawSalary = salaryEl ? salaryEl.innerText.trim() : "";
        let salary = "";
        let salaryEnglish = "";

        if (rawSalary) {
            // $140k – $180k • 0.02% – 0.4%
            const parts = rawSalary.split('•');
            const moneyPart = parts[0].trim(); // "$140k – $180k"
            const rawEquity = parts[1] ? parts[1].trim() : "";

            // 提取数字并乘 7.2 / 12
            const moneyMatches = moneyPart.match(/\$(\d+)[kK]/g);
            if (moneyMatches && moneyMatches.length >= 1) {
                const convert = (valStr) => {
                    const num = parseInt(valStr.replace(/[\$\,kK]/g, ''));
                    return Math.round(num * 7.2 / 12);
                };
                
                const minVal = convert(moneyMatches[0]);
                const maxVal = moneyMatches[1] ? convert(moneyMatches[1]) : minVal;
                
                const formattedRange = minVal === maxVal ? `${minVal}K` : `${minVal}-${maxVal}K`;
                
                // 股权合法性判断：必须包含数字（排除 "No equity"）
                const hasEquity = /\d/.test(rawEquity);
                const cleanEquity = hasEquity ? rawEquity.replace(/\s+/g, '') : ""; // 去掉空格
                
                const finalSalaryBase = formattedRange + (cleanEquity ? `·${cleanEquity}` : "");
                salary = finalSalaryBase + (hasEquity ? "股" : "");
                salaryEnglish = finalSalaryBase;
            } else {
                salary = rawSalary.replace(/\s+/g, '');
                salaryEnglish = rawSalary.replace(/\s+/g, '');
            }
        }

        // 1. Location(s) 逻辑
        let city = "";
        const locationDT = allDTs.find(dt => dt.innerText.trim() === 'Location' || dt.innerText.trim() === 'Locations');
        if (locationDT) {
            const locationDD = locationDT.nextElementSibling;
            if (locationDD) {
                const liTags = locationDD.querySelectorAll('li');
                if (liTags.length > 0) {
                    city = Array.from(liTags).map(li => li.innerText.trim()).join(', ');
                } else {
                    city = locationDD.innerText.trim();
                }
            }
        }
        
        // 4. Markets / Summary 逻辑
        let marketsSummary = "";
        const marketsDT = allDTs.find(dt => dt.innerText.trim() === 'Markets');
        if (marketsDT) {
            const marketsDD = marketsDT.nextElementSibling;
            if (marketsDD) {
                const spans = marketsDD.querySelectorAll('a span');
                marketsSummary = Array.from(spans).map(s => s.innerText.trim()).join(', ');
            }
        }

        // Experience
        let experience = "";
        const expDT = allDTs.find(dt => dt.innerText.trim().includes('Experience'));
        if (expDT) {
            const expDD = expDT.nextElementSibling;
            experience = expDD ? expDD.innerText.trim() : "";
        }

        // Calculate createdAt
        let createdAt = "";
        const spans = document.querySelectorAll('span');
        for (let span of spans) {
            const text = span.innerText.trim().toLowerCase();
            if (text.startsWith('posted') && text.includes('ago')) {
                const match = text.match(/(\d+)\s+days?\s+ago/);
                if (match) {
                     const daysAgo = parseInt(match[1]);
                     const date = new Date();
                     date.setDate(date.getDate() - daysAgo);
                     createdAt = date.toISOString().split('T')[0];
                } else if (text.includes('today')) {
                    createdAt = new Date().toISOString().split('T')[0];
                } else if (text.includes('yesterday')) {
                    const date = new Date();
                     date.setDate(date.getDate() - 1);
                     createdAt = date.toISOString().split('T')[0];
                }
                break;
            }
        }
        
        const headerTitle = document.querySelector('h1') || document.querySelector('.styles_header__Ww_7v');
        const title = headerTitle ? headerTitle.innerText.trim() : "";
        
        const companyLink = document.querySelector('a[href^="/company/"]');
        const team = companyLink ? companyLink.innerText.trim() : "";

        const detail = {
            source_url: window.location.href.split('?')[0],
            title: title,
            description: description,
            salary: salary,
            salary_english: salaryEnglish,
            experience: experience,
            city: city,
            team: team,
            createdAt: createdAt,
            summary: marketsSummary
        };

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
        window.location.reload(); 
    });
}

async function runAutoPilot() {
    const pageType = getPageType();
    if (pageType === 'detail') {
        const res = await scrapeDetail();
        if (!res.success) {
            // If failed, maybe we are not on a detail page or captcha?
            // Wait a bit
        }
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
    // Port 5002 for Wellfound
    const server_url = `http://127.0.0.1:5002${endpoint}`;
    
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
