// 智联招聘采集桥 - Background Script
// 用于代理 Content Script 的请求，避开 CORS 和私有网络限制

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'FETCH') {
        const { url, options } = request.data;
        
        fetch(url, options)
            .then(async response => {
                const text = await response.text();
                let data;
                try {
                    data = JSON.parse(text);
                } catch (e) {
                    data = text;
                }
                
                sendResponse({ 
                    success: response.ok, 
                    status: response.status,
                    data: data 
                });
            })
            .catch(error => {
                console.error('Background Fetch Error:', error);
                sendResponse({ 
                    success: false, 
                    error: error.message 
                });
            });
            
        return true; // 保持通道开启以进行异步回答
    }
});
