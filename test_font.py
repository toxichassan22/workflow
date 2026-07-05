import sys
sys.path.insert(0, r'D:\workflow\read')
from pdf_generator_html import generate_pdf

test_slides = [
    {'type': 'cover', 'title': 'اختبار الفونت العربي', 'subtitle': 'اختبار خط The Sans Arabic',
     'design': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#7A0C0C',
                'text_color': '#FFFFFF', 'layout': 'centered', 'title_style': 'large_centered'}},
    {'type': 'content', 'title': 'اختبار النصوص العربية',
     'sections': [
         {'title': 'اختبار العناوين', 'type': 'list', 'items': [
             'أبجد هوز حطيكلمن سعفص قرشت',
             'هذا اختبار لخط The Sans Arabic',
             'النص يجب أن يظهر بخط عربي واضح وجميل',
         ]},
         {'title': 'اختبار الأرقام', 'type': 'list', 'items': [
             'الإيرادات: 1,234,567 ريال',
             'المصروفات: 890,123 ريال',
             'صافي الربح: 344,444 ريال',
         ]},
     ],
     'design': {'mood': 'modern', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                'secondary_color': '#C4A35A', 'accent_color': '#FBF6EE', 'bg_color': '#FBF6EE',
                'text_color': '#2D2D2D', 'layout': 'dashboard', 'title_style': 'top_bar'}},
    {'type': 'closing', 'title': 'شكراً لاهتمامكم', 'subtitle': 'منافع الاقتصادية للعقار',
     'design': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#5A0808',
                'text_color': '#FFFFFF', 'layout': 'centered'}}
]

output = generate_pdf(test_slides, 'اختبار_الفونت', r'D:\workflow\test_font_output.pdf')
print(f'PDF saved to: {output}')
