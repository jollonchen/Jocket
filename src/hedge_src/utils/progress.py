from datetime import datetime, timezone
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.style import Style
from rich.text import Text
from typing import Dict, Optional, Callable, List

console = Console()


class AgentProgress:
    """Manages progress tracking for multiple agents."""

    def __init__(self):
        self.agent_status: Dict[str, Dict[str, str]] = {}
        self.table = Table(show_header=False, box=None, padding=(0, 1))
        self.live = Live(self.table, console=console, refresh_per_second=4)
        self.started = False
        self.update_handlers: List[Callable[[str, Optional[str], str], None]] = []

    def register_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Register a handler to be called when agent status updates."""
        self.update_handlers.append(handler)
        return handler  # Return handler to support use as decorator

    def unregister_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Unregister a previously registered handler."""
        if handler in self.update_handlers:
            self.update_handlers.remove(handler)

    def start(self):
        """Start the progress display."""
        if not self.started:
            self.live.start()
            self.started = True

    def stop(self):
        """Stop the progress display."""
        if self.started:
            self.live.stop()
            self.started = False

    def update_status(self, agent_name: str, ticker: Optional[str] = None, status: str = "", analysis: Optional[str] = None):
        """Update the status of an agent."""
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {"status": "", "ticker": None}

        # Translate status to Chinese
        if status:
            status_map = {
                "preparing hedge fund run": "准备对冲基金系统运行",
                "processing analyst signals": "处理分析师投研信号",
                "generating trading decisions": "生成最终交易决策",
                "fetching financial metrics": "获取财务指标",
                "gathering financial line items": "提取财务报表项",
                "fetching financial line items": "提取财务报表项",
                "getting market cap": "获取市值",
                "fetching insider trades": "获取内部持股变动",
                "fetching company news": "获取相关公司新闻",
                "analyzing moat strength": "分析核心竞争优势与护城河",
                "analyzing management quality": "评估企业管理层素养",
                "analyzing business predictability": "分析业务长期可预测性",
                "calculating munger-style valuation": "进行查理·芒格风格估值",
                "generating charlie munger analysis": "生成查理·芒格投研分析",
                "analyzing business quality": "分析业务品质与竞争力",
                "analyzing balance sheet and capital structure": "分析财务健康度与资本结构",
                "analyzing activism potential": "评估股东积极干预解锁空间",
                "calculating intrinsic value & margin of safety": "计算内在价值与安全边际",
                "generating bill ackman analysis": "生成比尔·阿克曼投研分析",
                "analyzing earnings stability": "分析盈利成长稳定性",
                "analyzing financial strength": "分析企业资本财务结构",
                "analyzing graham valuation": "进行格雷厄姆风格估值",
                "generating ben graham analysis": "生成本·格雷厄姆投研分析",
                "analyzing disruptive potential": "评估行业颠覆性成长潜能",
                "analyzing innovation-driven growth": "分析创新驱动型快速增长",
                "calculating valuation & high-growth scenario": "测算高成长情景公允估值",
                "generating cathie wood analysis": "生成凯茜·伍德投研分析",
                "fetching news sentiment": "获取最新新闻舆情数据",
                "analyzing news": "研判新闻利好与利空影响",
                "generating news sentiment analysis": "生成新闻舆情量化分析",
                "analyzing technical indicators": "计算多维度技术分析指标",
                "analyzing momentum": "研判价格趋势与相对动能",
                "analyzing price action": "研判多空价格行为特征",
                "analyzing trend": "研判长短期趋势运行方向",
                "analyzing support/resistance": "精确计算多空支撑与阻力位",
                "generating technical analysis": "生成技术指标深度研究报告",
                "analyzing growth trends": "追踪评估企业成长趋势",
                "analyzing valuation metrics": "分析各类常用估值乘数",
                "generating growth analysis": "生成企业成长效率分析",
                "analyzing sentiment metrics": "量化评估市场情绪指标",
                "analyzing market breath": "分析多空市场宽度与深度",
                "analyzing behavioral metrics": "研判资金流向与行为学特征",
                "generating sentiment analysis": "生成市场情绪面研究报告",
                "calculating valuation ratios": "精确计算各类估值比率",
                "performing relative valuation": "进行行业横向相对估值",
                "generating valuation analysis": "生成企业内在价值定价报告",
                "analyzing fundamentals": "分析底层企业基本面实力",
                "analyzing consistency": "评估长期盈利逻辑连续性",
                "analyzing pricing power": "研判产品定价权及抗通胀能力",
                "analyzing book value growth": "追踪账面净资产复利增长",
                "calculating intrinsic value": "计算内在价值中枢",
                "generating warren buffett analysis": "生成沃伦·巴菲特投研分析",
                "analyzing macro trends": "研判自上而下宏观趋势",
                "analyzing macro factors": "研判多项宏观变量因子",
                "analyzing risk-reward": "测算长期投资风险收益比",
                "analyzing insider activity": "追踪董监高内部持股变动",
                "analyzing sentiment": "研判情绪热度与多空偏好",
                "analyzing growth & momentum": "评估核心成长与趋势动能",
                "generating stanley druckenmiller analysis": "生成斯坦利·德鲁肯米勒投研分析",
                "performing druckenmiller-style valuation": "进行自上而下宏观资产估值",
                "generating phil fisher-style analysis": "生成菲利普·费雪投研分析",
                "analyzing valuation (fisher style)": "进行费雪式成长股估值",
                "analyzing management efficiency & leverage": "评估管理效能与资本结构",
                "analyzing margins & stability": "研判毛利稳定性与安全边际",
                "generating rakesh jhunjhunwala analysis": "生成拉克什·均均瓦拉投研分析",
                "analyzing emerging market opportunities": "研判新兴市场结构性机遇",
                "generating mohnish pabrai analysis": "生成莫尼什·帕伯莱投研分析",
                "generating aswath damodaran analysis": "生成阿斯瓦斯·达莫达兰投研分析",
                "analyzing growth and reinvestment": "分析企业资本支出与再投资",
                "analyzing risk profile": "测算系统与非系统性风险特征",
                "calculating intrinsic value (dcf)": "建立现金流折现（DCF）估值模型",
                "assessing relative valuation": "进行相对乘数合理估值评估",
                "generating damodaran analysis": "生成达莫达兰精细化估值报告",
                "generating michael burry analysis": "生成迈克尔·贝里投研分析",
                "analyzing macroeconomic conditions": "分析宏观图景与信用周期",
                "analyzing systemic risks": "评估市场潜在系统性危机特征",
                "analyzing tail risk & fragility": "评估尾部风险事件与抗压能力",
                "analyzing barbell allocations": "制定双峰哑铃式防御进攻策略",
                "generating nassim taleb analysis": "生成纳西姆·塔勒布反脆弱分析报告",
                "generating peter lynch analysis": "生成彼得·林奇投研分析",
                "analyzing capital allocation": "评估董事会资本开支与回购分红",
                "done": "完成",
                "error": "错误",
            }

            status_lower = status.strip().lower()
            if status_lower in status_map:
                status = status_map[status_lower]
            else:
                import re
                m = re.match(r'generating (.+?) analysis', status_lower)
                if m:
                    agent_p = m.group(1).replace("_", " ").title()
                    ch_name = self._get_display_name(agent_p)
                    status = f"生成{ch_name}投研分析"
                else:
                    m2 = re.match(r'performing (.+?)-style valuation', status_lower)
                    if m2:
                        agent_p = m2.group(1).replace("_", " ").title()
                        ch_name = self._get_display_name(agent_p)
                        status = f"进行{ch_name}风格估值"

        if ticker:
            self.agent_status[agent_name]["ticker"] = ticker
        if status:
            self.agent_status[agent_name]["status"] = status
        if analysis:
            self.agent_status[agent_name]["analysis"] = analysis

        # Set the timestamp as UTC datetime
        timestamp = datetime.now(timezone.utc).isoformat()
        self.agent_status[agent_name]["timestamp"] = timestamp

        # Notify all registered handlers
        for handler in self.update_handlers:
            handler(agent_name, ticker, status, analysis, timestamp)

        self._refresh_display()

    def get_all_status(self):
        """Get the current status of all agents as a dictionary."""
        return {agent_name: {"ticker": info["ticker"], "status": info["status"], "display_name": self._get_display_name(agent_name)} for agent_name, info in self.agent_status.items()}

    def _get_display_name(self, agent_name: str) -> str:
        """Convert agent_name to a Chinese display name if possible."""
        name_map = {
            "aswath_damodaran": "阿斯瓦斯·达莫达兰",
            "ben_graham": "本·格雷厄姆",
            "bill_ackman": "比尔·阿克曼",
            "cathie_wood": "凯茜·伍德",
            "charlie_munger": "查理·芒格",
            "michael_burry": "迈克尔·贝里",
            "mohnish_pabrai": "莫尼什·帕伯莱",
            "nassim_taleb": "纳西姆·塔勒布",
            "peter_lynch": "彼得·林奇",
            "phil_fisher": "菲利普·费雪",
            "rakesh_jhunjhunwala": "拉克什·均均瓦拉",
            "stanley_druckenmiller": "斯坦利·德鲁肯米勒",
            "warren_buffett": "沃伦·巴菲特",
            "technical_analyst": "技术指标分析师",
            "fundamentals_analyst": "基本面分析师",
            "growth_analyst": "成长型分析师",
            "news_sentiment_analyst": "新闻舆情分析师",
            "sentiment_analyst": "情绪分析师",
            "valuation_analyst": "估值分析师",
            "portfolio_manager": "投资组合经理",
            "risk_management_agent": "风控经理",
            "risk_management": "风控经理",
            "system": "系统",
            "backtest": "历史回测",
        }
        clean_name = agent_name.replace("_agent", "").strip().lower()
        import re
        clean_name_stripped = re.sub(r'_\d+$', '', clean_name)

        if clean_name_stripped in name_map:
            return name_map[clean_name_stripped]
        return clean_name.replace("_", " ").title()

    def _refresh_display(self):
        """Refresh the progress display."""
        self.table.columns.clear()
        self.table.add_column(width=100)

        # Sort agents with Risk Management and Portfolio Management at the bottom
        def sort_key(item):
            agent_name = item[0]
            if "risk_management" in agent_name:
                return (2, agent_name)
            elif "portfolio_management" in agent_name:
                return (3, agent_name)
            else:
                return (1, agent_name)

        for agent_name, info in sorted(self.agent_status.items(), key=sort_key):
            status = info["status"]
            ticker = info["ticker"]
            # Create the status text with appropriate styling
            if status.lower() == "done":
                style = Style(color="green", bold=True)
                symbol = "✓"
            elif status.lower() == "error":
                style = Style(color="red", bold=True)
                symbol = "✗"
            else:
                style = Style(color="yellow")
                symbol = "⋯"

            agent_display = self._get_display_name(agent_name)
            status_text = Text()
            status_text.append(f"{symbol} ", style=style)
            status_text.append(f"{agent_display:<20}", style=Style(bold=True))

            if ticker:
                status_text.append(f"[{ticker}] ", style=Style(color="cyan"))
            status_text.append(status, style=style)

            self.table.add_row(status_text)


# Create a global instance
progress = AgentProgress()
