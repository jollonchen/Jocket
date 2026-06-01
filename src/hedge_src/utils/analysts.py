"""Constants and utilities related to analysts configuration."""

from src.hedge_src.agents import portfolio_manager
from src.hedge_src.agents.aswath_damodaran import aswath_damodaran_agent
from src.hedge_src.agents.ben_graham import ben_graham_agent
from src.hedge_src.agents.bill_ackman import bill_ackman_agent
from src.hedge_src.agents.cathie_wood import cathie_wood_agent
from src.hedge_src.agents.charlie_munger import charlie_munger_agent
from src.hedge_src.agents.fundamentals import fundamentals_analyst_agent
from src.hedge_src.agents.michael_burry import michael_burry_agent
from src.hedge_src.agents.phil_fisher import phil_fisher_agent
from src.hedge_src.agents.peter_lynch import peter_lynch_agent
from src.hedge_src.agents.sentiment import sentiment_analyst_agent
from src.hedge_src.agents.stanley_druckenmiller import stanley_druckenmiller_agent
from src.hedge_src.agents.technicals import technical_analyst_agent
from src.hedge_src.agents.valuation import valuation_analyst_agent
from src.hedge_src.agents.warren_buffett import warren_buffett_agent
from src.hedge_src.agents.rakesh_jhunjhunwala import rakesh_jhunjhunwala_agent
from src.hedge_src.agents.mohnish_pabrai import mohnish_pabrai_agent
from src.hedge_src.agents.nassim_taleb import nassim_taleb_agent
from src.hedge_src.agents.news_sentiment import news_sentiment_agent
from src.hedge_src.agents.growth_agent import growth_analyst_agent

# Define analyst configuration - single source of truth
ANALYST_CONFIG = {
    "aswath_damodaran": {
        "display_name": "阿斯瓦斯·达莫达兰",
        "description": "估值界泰斗",
        "investing_style": "专注于内在价值与基本面，通过严谨的现金流折现（DCF）与相对估值模型精确评估投资机会。",
        "agent_func": aswath_damodaran_agent,
        "type": "analyst",
        "order": 0,
    },
    "ben_graham": {
        "display_name": "本·格雷厄姆",
        "description": "价值投资之父",
        "investing_style": "坚守安全边际，通过系统性的资产负债表与净流动资产（NCAV）评估，发掘具有高性价比的价值洼地公司。",
        "agent_func": ben_graham_agent,
        "type": "analyst",
        "order": 1,
    },
    "bill_ackman": {
        "display_name": "比尔·阿克曼",
        "description": "激进投资者",
        "investing_style": "奉行高集中度投资，倾向于通过公开倡导变革和重组，主动干预公司管理来解锁潜在的企业价值。",
        "agent_func": bill_ackman_agent,
        "type": "analyst",
        "order": 2,
    },
    "cathie_wood": {
        "display_name": "凯茜·伍德",
        "description": "成长股女皇",
        "investing_style": "专注于颠覆性技术和极具增长空间的创新行业，前瞻性投资于能重塑社会生产力的先锋科技企业。",
        "agent_func": cathie_wood_agent,
        "type": "analyst",
        "order": 3,
    },
    "charlie_munger": {
        "display_name": "查理·芒格",
        "description": "理性思考者",
        "investing_style": "倡导多学科决策模型，推崇长期持有拥有强大护城河、轻资本运营、治理结构卓越的高品质公司。",
        "agent_func": charlie_munger_agent,
        "type": "analyst",
        "order": 4,
    },
    "michael_burry": {
        "display_name": "迈克尔·贝里",
        "description": "大空头逆向者",
        "investing_style": "践行深度逆向投资，善于通过掘金资产负债表发现被市场严重偏离的价格，并在极度高估的市场中敢于做空。",
        "agent_func": michael_burry_agent,
        "type": "analyst",
        "order": 5,
    },
    "mohnish_pabrai": {
        "display_name": "莫尼什·帕伯莱",
        "description": "丹多投资者",
        "investing_style": "秉持“下行风险极小，上行空间极大”的丹多核心思想，精选业务简单、被低估且管理层能力出众的企业。",
        "agent_func": mohnish_pabrai_agent,
        "type": "analyst",
        "order": 6,
    },
    "nassim_taleb": {
        "display_name": "纳西姆·塔勒布",
        "description": "黑天鹅风险分析师",
        "investing_style": "高度关注尾部风险、脆弱性与反脆弱性。避免高度依赖债务的公司，寻找下行有限而上行无限的凸性机会。",
        "agent_func": nassim_taleb_agent,
        "type": "analyst",
        "order": 7,
    },
    "peter_lynch": {
        "display_name": "彼得·林奇",
        "description": "十倍股猎手",
        "investing_style": "践行“投资你所了解的领域”，在日常生活中发现商机，寻找 PEG 合理、商业模式简单易懂的高成长性“十倍股”企业。",
        "agent_func": peter_lynch_agent,
        "type": "analyst",
        "order": 8,
    },
    "phil_fisher": {
        "display_name": "菲利普·费雪",
        "description": "闲聊调查法大师",
        "investing_style": "推崇成长型企业投资，擅长运用“闲聊调查法”（Scuttlebutt）对企业的商业壁垒、管理素养及研发实力进行全方位打听与求证。",
        "agent_func": phil_fisher_agent,
        "type": "analyst",
        "order": 9,
    },
    "rakesh_jhunjhunwala": {
        "display_name": "拉克什·均均瓦拉",
        "description": "印度大牛市推手",
        "investing_style": "立足宏观趋势与行业成长大局，前瞻重仓处于起跑线上且具备高成长性的新兴市场龙头公司。",
        "agent_func": rakesh_jhunjhunwala_agent,
        "type": "analyst",
        "order": 10,
    },
    "stanley_druckenmiller": {
        "display_name": "斯坦利·德鲁肯米勒",
        "description": "宏观投资大师",
        "investing_style": "擅长自上而下的全球宏观投资模型，敏锐捕捉由央行决策、流动性溢溢和经济政策周期引发的史诗级资产配置机会。",
        "agent_func": stanley_druckenmiller_agent,
        "type": "analyst",
        "order": 11,
    },
    "warren_buffett": {
        "display_name": "沃伦·巴菲特",
        "description": "奥马哈先知",
        "investing_style": "价值投资与品质企业的终极践行者。长线重仓具有宽阔经济护城河、稳定盈利历史、高 ROE 以及资本分红优良的旗舰企业。",
        "agent_func": warren_buffett_agent,
        "type": "analyst",
        "order": 12,
    },
    "technical_analyst": {
        "display_name": "技术指标分析师",
        "description": "图表形态专家",
        "investing_style": "基于量价特征、趋势线、支撑阻力位及主流震荡指标，对行情的多空动能进行纯粹的技术形态测算与交易策略捕捉。",
        "agent_func": technical_analyst_agent,
        "type": "analyst",
        "order": 13,
    },
    "fundamentals_analyst": {
        "display_name": "基本面分析师",
        "description": "财务报表专家",
        "investing_style": "深度审计历史财务指标，从净利润增长率、债务健康度、ROE 和毛利率演变等角度客观评测公司的内在资产质量。",
        "agent_func": fundamentals_analyst_agent,
        "type": "analyst",
        "order": 14,
    },
    "growth_analyst": {
        "display_name": "成长型分析师",
        "description": "成长与动能专家",
        "investing_style": "追踪行业趋势、营收复合增速以及业务成长爆发性，精选出具备优异成长效率与高扩张空间的红利期企业。",
        "agent_func": growth_analyst_agent,
        "type": "analyst",
        "order": 15,
    },
    "news_sentiment_analyst": {
        "display_name": "新闻舆情分析师",
        "description": "新闻舆情监测专家",
        "investing_style": "全面捕获和量化全球财经媒体及舆论热点，实时追踪公司情绪变化以精确把握事件驱动带来的短期套利机会。",
        "agent_func": news_sentiment_agent,
        "type": "analyst",
        "order": 16,
    },
    "sentiment_analyst": {
        "display_name": "情绪分析师",
        "description": "市场情绪分析专家",
        "investing_style": "洞察市场参与者的心理状态和群羊效应，利用情绪波动指数（如 Fear & Greed Index）为交易提供极其理性的逆向操作参考。",
        "agent_func": sentiment_analyst_agent,
        "type": "analyst",
        "order": 17,
    },
    "valuation_analyst": {
        "display_name": "估值分析师",
        "description": "企业估值定价专家",
        "investing_style": "熟练编排多种绝对估值与相对估值定价模型，为企业测算内在价值空间，判定当前资产定价是否存在高估或低估。",
        "agent_func": valuation_analyst_agent,
        "type": "analyst",
        "order": 18,
    },
}

# Derive ANALYST_ORDER from ANALYST_CONFIG for backwards compatibility
ANALYST_ORDER = [(config["display_name"], key) for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"])]


def get_analyst_nodes():
    """Get the mapping of analyst keys to their (node_name, agent_func) tuples."""
    return {key: (f"{key}_agent", config["agent_func"]) for key, config in ANALYST_CONFIG.items()}


def get_agents_list():
    """Get the list of agents for API responses."""
    return [
        {
            "key": key,
            "display_name": config["display_name"],
            "description": config["description"],
            "investing_style": config["investing_style"],
            "order": config["order"]
        }
        for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"])
    ]
