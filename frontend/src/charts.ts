import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { AxisPointerComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([CustomChart, LineChart, AxisPointerComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
