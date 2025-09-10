// js_renderer.js - Puppeteer-based JavaScript renderer
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

class JSRenderer {
    constructor() {
        this.browser = null;
        this.pages = new Map();
        this.maxPages = 10;
    }

    async init() {
        try {
            this.browser = await puppeteer.launch({
                headless: true,
                args: [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu'
                ]
            });
            console.log('Browser initialized successfully');
        } catch (error) {
            console.error('Failed to initialize browser:', error);
            throw error;
        }
    }

    async getPage() {
        if (this.pages.size >= this.maxPages) {
            // Close oldest page
            const oldestPage = this.pages.values().next().value;
            await oldestPage.close();
            this.pages.delete(this.pages.keys().next().value);
        }

        const page = await this.browser.newPage();
        const pageId = Date.now() + Math.random();
        this.pages.set(pageId, page);

        // Set viewport and user agent
        await page.setViewport({ width: 1920, height: 1080 });
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36');

        return { page, pageId };
    }

    async renderPage(url, options = {}) {
        const {
            proxy = null,
            timeout = 30000,
            waitFor = 'networkidle2',
            screenshot = false,
            extractData = null,
            blockResources = ['image', 'stylesheet', 'font']
        } = options;

        let page, pageId;
        
        try {
            const pageData = await this.getPage();
            page = pageData.page;
            pageId = pageData.pageId;

            // Set up proxy authentication if needed
            if (proxy && proxy.username) {
                await page.authenticate({
                    username: proxy.username,
                    password: proxy.password
                });
            }

            // Block unnecessary resources to speed up loading
            if (blockResources.length > 0) {
                await page.setRequestInterception(true);
                page.on('request', (req) => {
                    if (blockResources.includes(req.resourceType())) {
                        req.abort();
                    } else {
                        req.continue();
                    }
                });
            }

            // Handle JavaScript errors and console messages
            page.on('pageerror', error => {
                console.log(`Page error: ${error.message}`);
            });

            page.on('console', msg => {
                if (msg.type() === 'error') {
                    console.log(`Console error: ${msg.text()}`);
                }
            });

            // Navigate to page
            const response = await page.goto(url, { 
                waitUntil: waitFor, 
                timeout: timeout 
            });

            if (!response.ok()) {
                throw new Error(`HTTP ${response.status()}: ${response.statusText()}`);
            }

            // Wait for additional content to load
            await page.waitForTimeout(2000);

            const result = {
                url: url,
                status: response.status(),
                timestamp: new Date().toISOString(),
                content: await page.content()
            };

            // Extract specific data if selector provided
            if (extractData) {
                result.extractedData = {};
                for (const [key, selector] of Object.entries(extractData)) {
                    try {
                        const elements = await page.$$(selector);
                        const data = [];
                        for (const element of elements) {
                            const text = await page.evaluate(el => el.textContent, element);
                            const html = await page.evaluate(el => el.innerHTML, element);
                            data.push({ text: text.trim(), html });
                        }
                        result.extractedData[key] = data;
                    } catch (e) {
                        result.extractedData[key] = [];
                    }
                }
            }

            // Take screenshot if requested
            if (screenshot) {
                result.screenshot = await page.screenshot({ 
                    encoding: 'base64',
                    fullPage: true 
                });
            }

            return result;

        } catch (error) {
            console.error(`Rendering error for ${url}:`, error.message);
            return {
                url: url,
                error: error.message,
                timestamp: new Date().toISOString(),
                content: null
            };
        } finally {
            if (page && pageId) {
                try {
                    await page.close();
                    this.pages.delete(pageId);
                } catch (e) {
                    console.error('Error closing page:', e);
                }
            }
        }
    }

    async batchRender(urls, options = {}) {
        const { maxConcurrent = 3 } = options;
        const results = [];
        
        // Process URLs in batches to avoid overwhelming the browser
        for (let i = 0; i < urls.length; i += maxConcurrent) {
            const batch = urls.slice(i, i + maxConcurrent);
            const batchPromises = batch.map(url => this.renderPage(url, options));
            const batchResults = await Promise.allSettled(batchPromises);
            
            batchResults.forEach((result, index) => {
                if (result.status === 'fulfilled') {
                    results.push(result.value);
                } else {
                    results.push({
                        url: batch[index],
                        error: result.reason.message,
                        timestamp: new Date().toISOString(),
                        content: null
                    });
                }
            });

            // Small delay between batches
            if (i + maxConcurrent < urls.length) {
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
        }

        return results;
    }

    async close() {
        if (this.browser) {
            await this.browser.close();
            this.browser = null;
            this.pages.clear();
        }
    }
}

// Advanced content analysis
class ContentAnalyzer {
    static analyzeContent(content) {
        const analysis = {
            hasJavaScript: /<script/i.test(content),
            hasFrames: /<iframe|<frame/i.test(content),
            hasAjax: /ajax|xhr|fetch/i.test(content),
            hasReactVue: /react|vue|angular/i.test(content),
            hasCaptcha: /captcha|recaptcha/i.test(content),
            hasCloudflare: /cloudflare/i.test(content),
            hasBlocking: /access denied|blocked|forbidden/i.test(content),
            contentLength: content.length,
            loadTime: null
        };

        return analysis;
    }

    static detectAntiBot(content) {
        const antibotPatterns = [
            /cf-browser-verification/i,
            /challenge-form/i,
            /distil-ident-block/i,
            /imperva|incapsula/i,
            /bot detection/i,
            /please enable javascript/i,
            /cloudflare.*checking/i
        ];

        return antibotPatterns.some(pattern => pattern.test(content));
    }
}

// CLI interface for testing
if (require.main === module) {
    const [,, command, ...args] = process.argv;

    async function handleCommand() {
        const renderer = new JSRenderer();
        await renderer.init();

        try {
            switch (command) {
                case 'render': {
                    const url = args[0];
                    if (!url) {
                        console.error('URL required');
                        process.exit(1);
                    }
                    
                    const result = await renderer.renderPage(url, {
                        extractData: {
                            title: 'title',
                            headings: 'h1, h2, h3',
                            links: 'a[href]'
                        }
                    });
                    
                    console.log(JSON.stringify(result, null, 2));
                    break;
                }

                case 'batch': {
                    const urls = args;
                    if (urls.length === 0) {
                        console.error('URLs required');
                        process.exit(1);
                    }

                    const results = await renderer.batchRender(urls);
                    console.log(JSON.stringify(results, null, 2));
                    break;
                }

                case 'analyze': {
                    const url = args[0];
                    if (!url) {
                        console.error('URL required');
                        process.exit(1);
                    }

                    const result = await renderer.renderPage(url);
                    const analysis = ContentAnalyzer.analyzeContent(result.content);
                    const hasAntiBot = ContentAnalyzer.detectAntiBot(result.content);
                    
                    console.log(JSON.stringify({
                        ...result,
                        analysis,
                        hasAntiBot
                    }, null, 2));
                    break;
                }

                default:
                    console.log(`
Usage: node js_renderer.js <command> [args]

Commands:
  render <url>           - Render single page
  batch <url1> <url2>... - Render multiple pages
  analyze <url>          - Analyze page content

Examples:
  node js_renderer.js render https://example.com
  node js_renderer.js batch https://site1.com https://site2.com
  node js_renderer.js analyze https://protected-site.com
                    `);
            }
        } finally {
            await renderer.close();
        }
    }

    handleCommand().catch(console.error);
}

module.exports = { JSRenderer, ContentAnalyzer };

// Package.json for dependencies
const packageJson = {
    "name": "intelligent-scraper-renderer",
    "version": "1.0.0",
    "description": "JavaScript renderer for intelligent scraper",
    "main": "js_renderer.js",
    "dependencies": {
        "puppeteer": "^19.0.0"
    },
    "scripts": {
        "install-deps": "npm install",
        "test": "node js_renderer.js analyze https://httpbin.org/html"