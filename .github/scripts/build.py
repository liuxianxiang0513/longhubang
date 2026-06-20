#!/usr/bin/env python3
"""
GitHub Actions 用：直接从 AKShare 获取龙虎榜数据，生成静态 HTML。
独立运行，不依赖 lhb_server.py。
"""
import json, re, sys, urllib.request, os
from datetime import datetime

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
TEMPLATE = 'index_template.html'

# ── 1. 获取龙虎榜个股列表 ──
def fetch_lhb_stocks(date_str=None):
    """使用东方财富 DataCenter_V3 接口获取龙虎榜个股"""
    import akshare as ak
    df = ak.stock_lhb_stock_detail_em(date=date_str or "20260618")
    return df

# ── 2. 获取个股营业部明细 ──
def fetch_stock_detail(code, date_str="2026-06-18"):
    import akshare as ak
    try:
        df = ak.stock_lhb_stock_detail_em(date=date_str)
        # 筛选该个股
        stock_rows = df[df['代码'] == code] if '代码' in df.columns else df
        return stock_rows
    except Exception as e:
        print(f"  fetch error {code}: {e}", file=sys.stderr)
        return None

# ── 3. 格式化金额 ──
def fmt(n):
    if n is None or n == 0:
        return 0
    return round(float(n), 2)

def main():
    print("📡 获取龙虎榜数据...")
    
    import akshare as ak
    
    # 尝试获取最近交易日数据
    today = datetime.now().strftime("%Y%m%d")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        df = ak.stock_lhb_stock_detail_em(date=date_str)
        actual_date = today
    except Exception as e:
        print(f"  today failed ({e}), trying 20260618")
        df = ak.stock_lhb_stock_detail_em(date="2026-06-18")
        actual_date = "20260618"
    
    print(f"  获取到 {len(df)} 行数据")
    
    # 按营业部聚合
    col_map = {}
    for c in df.columns:
        col_map[c] = c
    
    def get_col(row, *names):
        for n in names:
            if n in row.index:
                return row[n]
        return 0
    
    # 聚合
    traders = {}
    stocks_set = set()
    
    for _, row in df.iterrows():
        code = str(get_col(row, '代码', 'code')).strip()
        name = str(get_col(row, '名称', 'name')).strip()
        dept = str(get_col(row, '营业部名称', '营业部', 'department')).strip()
        buy = fmt(get_col(row, '买入金额', '买入额'))
        sell = fmt(get_col(row, '卖出金额', '卖出额'))
        net = buy - sell
        
        if not dept or dept == 'nan':
            continue
        
        stocks_set.add(code)
        
        if dept not in traders:
            traders[dept] = {
                'name': dept,
                'total_buy': 0,
                'total_sell': 0,
                'total_net': 0,
                'stocks': [],
            }
        
        t = traders[dept]
        t['total_buy'] += buy
        t['total_sell'] += sell
        t['total_net'] += net
        t['stocks'].append({
            'code': code,
            'name': name,
            'buy': buy,
            'sell': sell,
            'net': net,
        })
    
    trader_list = list(traders.values())
    for t in trader_list:
        t['stock_count'] = len(t['stocks'])
        t['total_buy'] = round(t['total_buy'], 2)
        t['total_sell'] = round(t['total_sell'], 2)
        t['total_net'] = round(t['total_net'], 2)
    
    # 按净买入排序
    trader_list.sort(key=lambda x: x['total_net'], reverse=True)
    
    total_buy = round(sum(t['total_buy'] for t in trader_list), 2)
    total_sell = round(sum(t['total_sell'] for t in trader_list), 2)
    total_net = round(total_buy - total_sell, 2)
    
    # 构建数据结构
    stocks_list = []
    for c in sorted(stocks_set):
        stocks_list.append({'code': c, 'name': ''})
    
    data = {
        'overview': {
            'date': actual_date,
            'stocks': stocks_list,
            'stock_count': len(stocks_set),
            'update': datetime.now().strftime('%H:%M:%S'),
        },
        'detail': {
            'traders': trader_list,
            'total_buy': total_buy,
            'total_sell': total_sell,
            'total_net': total_net,
            'stocks_scanned': len(stocks_set),
        },
    }
    
    print(f"✅ 完成: {len(stocks_set)} 只股票, {len(trader_list)} 个席位")
    print(f"   总买入: {total_buy:.2f}  总卖出: {total_sell:.2f}  净: {total_net:.2f}")
    
    # 读取模板
    if not os.path.exists(TEMPLATE):
        print(f"❌ 模板 {TEMPLATE} 不存在，使用内联模板")
        # 尝试从 index.html 读取（它应该包含 __INJECT_DATA__ 占位符）
        if os.path.exists(OUTPUT):
            with open(OUTPUT, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            print("❌ 无模板可用")
            sys.exit(1)
    else:
        with open(TEMPLATE, 'r', encoding='utf-8') as f:
            template = f.read()
    
    # 注入数据
    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # 转义给 JS 字符串用
    escaped = json_str.replace('\\', '\\\\').replace('"', '\\"')
    
    if '__INJECT_DATA__' in template:
        result = template.replace('"__INJECT_DATA__"', f'"{escaped}"')
        print(f"  替换占位符完成")
    else:
        # 替换已有 STATIC_DATA
        result = re.sub(
            r'const STATIC_DATA = ".*?";',
            f'const STATIC_DATA = "{escaped}";',
            template,
            flags=re.DOTALL,
        )
        if result == template:
            print("⚠️ 未找到占位符或 STATIC_DATA，尝试直接替换...")
            # 尝试找 STATIC_DATA = { ... } 格式
            result = re.sub(
                r'STATIC_DATA = ({.*?});\s*$',
                f'STATIC_DATA = {json_str};',
                template,
                flags=re.DOTALL | re.MULTILINE,
            )
    
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(result)
    
    file_size = os.path.getsize(OUTPUT)
    print(f"✅ 已写入: {OUTPUT} ({file_size:,} bytes)")

if __name__ == '__main__':
    main()
