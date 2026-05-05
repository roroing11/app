import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import numpy as np
from decimal import Decimal # 🚨 정밀 계산 타입을 불러옵니다

# ---------------------------------------------------------
# 🚨 [몽키 패치 수정본] Decimal 타입 충돌 에러 해결
# ---------------------------------------------------------
if not hasattr(Item, 'original_get_dimension'):
    Item.original_get_dimension = Item.get_dimension

def custom_get_dimension(self):
    # 만약 '세우기 강제' 옵션이 켜져 있다면
    if getattr(self, 'force_upright', False):
        # 0번(WHD)과 3번(DHW) 방향이 아니면 (눕혀지는 경우)
        if self.rotation_type not in [0, 3]:
            # 🚨 float 대신 Decimal 타입을 사용하여 계산 충돌 방지!
            return [Decimal('9999999.0'), Decimal('9999999.0'), Decimal('9999999.0')]
    return self.original_get_dimension()

Item.get_dimension = custom_get_dimension
# ---------------------------------------------------------

# --- 🚚 [화물차 제원 템플릿] ---
TRUCK_SPECS = {
    "1톤 윙바디 (까대기)": {"w": 1600, "h": 1600, "d": 2800, "max_w": 1200},
    "2.5톤 윙바디 (혼합)": {"w": 1900, "h": 2000, "d": 4300, "max_w": 2500},
    "5톤 윙바디 (파렛트)": {"w": 2350, "h": 2400, "d": 7400, "max_w": 5000},
    "11톤 윙바디 (파렛트)": {"w": 2400, "h": 2500, "d": 10200, "max_w": 11000},
}

PALLET_W = 1100
PALLET_D = 1100
PALLET_H = 150

# --- 🎯 [물리 엔진: 지지율 검증] ---
def apply_physics_engine(bin_data, min_support_ratio=0.7):
    if not bin_data.items: return []
    sorted_items = sorted(bin_data.items, key=lambda i: float(i.position[1]))
    dropped_boxes = [] 
    stable_items = []  
    rejected_items = [] 
    for item in sorted_items:
        x, y, z = map(float, item.position)
        w, h, d = map(float, item.get_dimension()) 
        max_floor_y = 0.0
        for dx, dy, dz, dw, dh, dd in dropped_boxes:
            overlap_x = not (x + w <= dx or x >= dx + dw)
            overlap_z = not (z + d <= dz or z >= dz + dd)
            if overlap_x and overlap_z:
                if dy + dh > max_floor_y: max_floor_y = dy + dh
        support_area = 0.0
        if max_floor_y == 0.0: support_area = w * d 
        else:
            for dx, dy, dz, dw, dh, dd in dropped_boxes:
                if abs((dy + dh) - max_floor_y) < 1.0:
                    ix_start = max(x, dx); ix_end = min(x + w, dx + dw)
                    iz_start = max(z, dz); iz_end = min(z + d, dz + dd)
                    if ix_start < ix_end and iz_start < iz_end:
                        support_area += (ix_end - ix_start) * (iz_end - iz_start)
        support_ratio = support_area / (w * d)
        if support_ratio >= min_support_ratio:
            item.position = [x, max_floor_y, z]
            dropped_boxes.append((x, max_floor_y, z, w, h, d))
            stable_items.append(item)
        else: rejected_items.append(item)
    bin_data.items = stable_items
    return rejected_items

# --- 🎯 [무게 중심 계산] ---
def calculate_center_of_gravity(bin_items):
    total_weight = sum([float(item.weight) for item in bin_items])
    if total_weight == 0: return 0, 0, 0, 0
    cg_x = sum([float(item.weight) * (float(item.position[0]) + float(item.width)/2) for item in bin_items]) / total_weight
    cg_y = sum([float(item.weight) * (float(item.position[1]) + float(item.height)/2) for item in bin_items]) / total_weight
    cg_z = sum([float(item.weight) * (float(item.position[2]) + float(item.depth)/2) for item in bin_items]) / total_weight
    return cg_x, cg_y, cg_z, total_weight

# --- [Plotly 3D 렌더링] ---
def create_plotly_figure(bin_data, use_pallet=False, original_truck_h=0):
    bin_w, bin_h, bin_d = float(bin_data.width), float(bin_data.height), float(bin_data.depth)
    display_h = original_truck_h if use_pallet else bin_h
    offset_z = PALLET_H if use_pallet else 0 
    fig = go.Figure()
    fig.add_trace(go.Mesh3d(
        x=[0, bin_d, bin_d, 0, 0, bin_d, bin_d, 0], y=[0, 0, bin_w, bin_w, 0, 0, bin_w, bin_w], z=[0, 0, 0, 0, display_h, display_h, display_h, display_h],
        alphahull=0, color='gray', opacity=0.05, name='화물칸 공간', flatshading=True, hoverinfo='none'
    ))
    if use_pallet:
        cols, rows = int(bin_w // PALLET_W), int(bin_d // PALLET_D)
        for r in range(rows):
            for c in range(cols):
                px0, py0 = r * PALLET_D, c * PALLET_W
                px1, py1 = px0 + PALLET_D, py0 + PALLET_W
                p_verts = np.array([[px0, py0, 0], [px1, py0, 0], [px1, py1, 0], [px0, py1, 0], [px0, py0, PALLET_H], [px1, py0, PALLET_H], [px1, py1, PALLET_H], [px0, py1, PALLET_H]])
                fig.add_trace(go.Mesh3d(x=p_verts[:, 0], y=p_verts[:, 1], z=p_verts[:, 2], i=[7,0,0,0,4,4,6,6,4,0,3,2], j=[3,4,1,2,5,6,5,2,0,1,6,3], k=[0,7,2,3,6,7,1,1,5,5,7,6], color='#8B5A2B', opacity=0.9, flatshading=True, showlegend=False, hoverinfo='none'))
                wrap_h = display_h * 0.8
                w_verts = np.array([[px0, py0, PALLET_H], [px1, py0, PALLET_H], [px1, py1, PALLET_H], [px0, py1, PALLET_H], [px0, py0, wrap_h], [px1, py0, wrap_h], [px1, py1, wrap_h], [px0, py1, wrap_h]])
                fig.add_trace(go.Mesh3d(x=w_verts[:, 0], y=w_verts[:, 1], z=w_verts[:, 2], i=[7,0,0,0,4,4,6,6,4,0,3,2], j=[3,4,1,2,5,6,5,2,0,1,6,3], k=[0,7,2,3,6,7,1,1,5,5,7,6], color='white', opacity=0.05, flatshading=True, showlegend=False, hoverinfo='none'))
    color_map = {'A형': '#FF4B4B', 'B형': '#FF9020', 'C형': '#F0E130', 'D형': '#2CA02C', 'E형': '#1F77B4'}
    for item in bin_data.items:
        if not item.position or len(item.position) != 3: continue
        item_x, item_y, item_z = map(float, item.position) 
        w, h, d = map(float, item.get_dimension()) 
        x0, y0, z0 = item_z, item_x, item_y + offset_z 
        x1, y1, z1 = item_z + d, item_x + w, item_y + h + offset_z
        verts = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
        color = 'cyan'
        for name_key, c_val in color_map.items():
            if name_key in item.name: color = c_val; break
        fig.add_trace(go.Mesh3d(x=verts[:, 0], y=verts[:, 1], z=verts[:, 2], i=[7,0,0,0,4,4,6,6,4,0,3,2], j=[3,4,1,2,5,6,5,2,0,1,6,3], k=[0,7,2,3,6,7,1,1,5,5,7,6], color=color, opacity=1.0, name=item.name, flatshading=True, showlegend=False))
        edges = [(0,1),(1,2),(2,3),(3,0), (4,5),(5,6),(6,7),(7,4), (0,4),(1,5),(2,6),(3,7)]
        for edge in edges: fig.add_trace(go.Scatter3d(x=[verts[edge[0]][0], verts[edge[1]][0]], y=[verts[edge[0]][1], verts[edge[1]][1]], z=[verts[edge[0]][2], verts[edge[1]][2]], mode='lines', line=dict(color='black', width=1), showlegend=False, hoverinfo='none'))
    cg_x, cg_y, cg_z, total_wt = calculate_center_of_gravity(bin_data.items)
    if total_wt > 0:
        fig.add_trace(go.Scatter3d(x=[cg_z], y=[cg_x], z=[cg_y + offset_z], mode='markers', marker=dict(size=12, color='red', symbol='cross'), name='화물 하중 중심 (CG)'))
        fig.add_trace(go.Scatter3d(x=[bin_d/2], y=[bin_w/2], z=[display_h/3], mode='markers', marker=dict(size=8, color='green', symbol='circle'), name='트럭 기하학 중심'))
    fig.update_layout(scene=dict(xaxis=dict(title='트럭 길이 (L, mm)', range=[0, bin_d]), yaxis=dict(title='트럭 폭 (W, mm)', range=[0, bin_w]), zaxis=dict(title='트럭 높이 (H, mm)', range=[0, display_h]), camera=dict(eye=dict(x=1.8, y=1.5, z=1.3)), aspectmode='data'), margin=dict(l=0, r=0, b=0, t=0), height=700, legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
    return fig, cg_x, cg_z

# =========================================================================
# 🌟 [Streamlit 웹페이지 디자인] 🌟
# =========================================================================

st.set_page_config(layout="wide", page_title="화물차 물류 적재 시뮬레이터")
st.title("🚚 화물차 3D 적재 시뮬레이터")

with st.sidebar:
    st.header("⚙️ 1. 차량 제원")
    template_choice = st.selectbox("템플릿", list(TRUCK_SPECS.keys()), index=2) 
    custom_w = st.number_input("폭 (W, mm)", value=TRUCK_SPECS[template_choice]["w"])
    custom_h = st.number_input("높이 (H, mm)", value=TRUCK_SPECS[template_choice]["h"])
    custom_d = st.number_input("길이 (L, mm)", value=TRUCK_SPECS[template_choice]["d"])
    custom_max_w = st.number_input("최대하중 (kg)", value=TRUCK_SPECS[template_choice]["max_w"])
    use_pallet = st.toggle("🪵 파렛트 & 랩핑 사용", value=True)
    clearance = st.slider("지게차 유격", 0, 200, 100)
    st.markdown("---")
    st.header("📦 2. 화물 세팅")
    box_configs = {}
    box_defaults = {
        'E형 ': {"w": 1000, "h": 1950, "d": 1000, "wt": 150, "cnt": 6},
        'D형 ': {"w": 800, "h": 1900, "d": 900, "wt": 120, "cnt": 4},
        'C형 ': {"w": 650, "h": 1700, "d": 750, "wt": 60, "cnt": 6},
        'B형 ': {"w": 550, "h": 900, "d": 600, "wt": 30, "cnt": 12},
        'A형 ': {"w": 500, "h": 300, "d": 400, "wt": 15, "cnt": 30}
    }
    for k, v in box_defaults.items():
        with st.expander(f"{k} 설정"):
            cnt = st.number_input(f"수량", value=v["cnt"], key=f"c_{k}")
            w = st.number_input("W", value=v["w"], key=f"w_{k}")
            h = st.number_input("H", value=v["h"], key=f"h_{k}")
            d = st.number_input("L", value=v["d"], key=f"d_{k}")
            wt = st.number_input("kg", value=v["wt"], key=f"wt_{k}")
            box_configs[k.split(' ')[0]] = {"w": w, "h": h, "d": d, "wt": wt, "cnt": cnt}
    st.markdown("---")
    force_upright = st.toggle("⬆️ 세워서 적재 강제", value=True)
    min_support = st.slider("안전 지지율 (%)", 10, 100, 70)
    run_btn = st.button("🚀 시뮬레이션 가동", type="primary")

if run_btn:
    packer = Packer()
    actual_calc_h = custom_h - PALLET_H - clearance if use_pallet else custom_h
    packer.add_bin(Bin("차량", custom_w, actual_calc_h, custom_d, custom_max_w))
    for bt in ['E형', 'D형', 'C형', 'B형', 'A형']:
        cfg = box_configs[bt]
        for i in range(cfg["cnt"]):
            item = Item(f'{bt}_{i+1}', cfg["w"], cfg["h"], cfg["d"], cfg["wt"])
            item.force_upright = force_upright # ⭐ 몽키 패치용 속성 주입
            packer.add_item(item)
    packer.pack()
    b = packer.bins[0]
    rejected = apply_physics_engine(b, min_support_ratio=(min_support/100.0))
    fig, cg_x, cg_z = create_plotly_figure(b, use_pallet=use_pallet, original_truck_h=custom_h)
    st.subheader("📊 시뮬레이션 리포트")
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 적재 상자", f"{len(b.items)} 개")
    c2.metric("📈 공간 활용률", f"{(sum([float(i.width)*float(i.height)*float(i.depth) for i in b.items]) / (custom_w*custom_h*custom_d)*100):.2f}%")
    c3.metric("⚖️ 하중 밸런스", f"{100 - abs(custom_d/2 - cg_z)/custom_d*100:.1f}점")
    st.plotly_chart(fig, use_container_width=True)