import os, sys, argparse, logging, cv2
import numpy as np
from PIL import Image
try:
    import simplejson as json
except ImportError:
    import json

# TODO: install.py for odin lib and remove this abomination
sys.path.append('../../')

from odin.libs.regions_of_interest.shapes_manager import Shape

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


class AutomaticCoresExtractor(object):

    def __init__(self, log_level='INFO', log_file=None):
        self.logger = self._get_logger(log_level, log_file)


    def _get_logger(self, log_level='INFO', log_file=None, mode='a'):
        LOG_FORMAT = '%(asctime)s|%(levelname)-8s|%(message)s'
        LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'

        logger = logging.getLogger('mask_applier')
        if not isinstance(log_level, int):
            try:
                log_level = getattr(logging, log_level)
            except AttributeError:
                raise ValueError('Unsupported literal log level: %s' % log_level)
        logger.setLevel(log_level)
        logger.handlers = []
        if log_file:
            handler = logging.FileHandler(log_file, mode=mode)
        else:
            handler = logging.StreamHandler()
        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def _get_slides_info(self, tiles_list, tile_img):
        height, width, _ = tile_img.shape
        ts = [os.path.split(t)[-1].split('.')[0] for t in tiles_list]
        rows = [int(t.split('_')[2]) + 1 for t in ts]
        columns = [int(t.split('_')[3]) + 1 for t in ts]
        zoom_level = int(ts[0].split('_')[1].split('-')[1])
        return max(rows) * height, max(columns) * width, zoom_level

    def _get_tiles_list(self, tiles_folder):
        return [os.path.join(tiles_folder, t) for t in os.listdir(tiles_folder) if t.endswith('.jpeg')]

    def _load_tile(self, tile_file):
        return cv2.imread(tile_file)

    def _get_tile_coordinate(self, tile_path):
        tile_fname = os.path.split(tile_path)[-1]
        _, _, row, col = tile_fname.split('.')[0].split('_')
        return row, col

    def _get_image_mask(self, img_height, img_width):
        return np.zeros((img_height, img_width), dtype=np.uint8)

    def _get_saturation_mask(self, tile_img):
        img_width, img_height, _ = tile_img.shape
        filter_mask = np.zeros((img_width, img_height), dtype=np.bool)
        hsv_image = cv2.cvtColor(tile_img, cv2.COLOR_BGR2HSV)
        for x in xrange(0, img_width):
            for y in xrange(0, img_height):
                if hsv_image[x, y, 1] > 20:
                    filter_mask[x, y] = 1
        return filter_mask

    def _find_tissue(self, tiles, image_mask):
        for t in tiles:
            tile_img = self._load_tile(t)
            saturation_mask = self._get_saturation_mask(tile_img)
            row, col = self._get_tile_coordinate(t)
            x = int(col) * tile_img.shape[0]
            y = int(row) * tile_img.shape[1]
            image_mask[y:y+tile_img.shape[1], x:x+tile_img.shape[0]] = saturation_mask

    def _contour_to_shape(self, contour):
        normalize_contour = list()
        for x in contour:
            normalize_contour.append(tuple(x[0]))
        try:
            return Shape(normalize_contour)
        except ValueError:
            return None

    def _get_cores(self, tissue_mask):
        _, contours, _ = cv2.findContours(tissue_mask, mode=cv2.RETR_EXTERNAL, method=cv2.CHAIN_APPROX_SIMPLE)
        contours = filter(None, [self._contour_to_shape(c) for c in contours])
        return contours

    def _filter_cores(self, cores, slide_area, core_min_area=0.02):
        accepted_cores = list()
        for core in cores:
            if (core.get_area()*100 / slide_area) >= core_min_area:
                accepted_cores.append(core)
        return accepted_cores

    def _get_sorted_cores_map(self, cores):
        cores_map = dict()
        for c in cores:
            bounds = c.get_bounds()
            cores_map.setdefault((bounds['y_min'], bounds['y_max']), []).append(c)
        sorted_y_coords = cores_map.keys()
        sorted_y_coords.sort(key=lambda x: x[0])
        return cores_map, sorted_y_coords

    def _group_nearest_cores(self, cores, slide_height, height_tolerance=0.01):
        cores_map, sorted_y_coords = self._get_sorted_cores_map(cores)
        cores_groups = list()
        tolerance = slide_height*height_tolerance
        current_group = cores_map[sorted_y_coords[0]]
        for i, yc in enumerate(sorted_y_coords[1:]):
            if yc[0] <= sorted_y_coords[i][1] + tolerance:
                current_group.extend(cores_map[yc])
            else:
                cores_groups.append(current_group)
                current_group = cores_map[yc]
        cores_groups.append(current_group)
        return cores_groups

    def _get_slice(self, cores_group):
        x_min = min([c.get_bounds()['x_min'] for c in cores_group])
        y_min = min([c.get_bounds()['y_min'] for c in cores_group])
        x_max = max([c.get_bounds()['x_max'] for c in cores_group])
        y_max = max([c.get_bounds()['y_max'] for c in cores_group])
        return Shape([(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)])

    def _build_slide_json(self, cores_group, scale_factor):
        slide_shapes = list()
        for group in cores_group:
            slice = self._get_slice(group)
            slice_map = {
                'coordinates': slice.get_coordinates(scale_factor),
                'cores': [
                    {'coordinates': c.get_coordinates(scale_factor),
                     'length': c.get_length()}
                    for c in group]
            }
            slide_shapes.append(slice_map)
        return slide_shapes

    def run(self, tiles_folder, output_file):
        tiles_list = self._get_tiles_list(tiles_folder)
        img_height, img_width, zoom_level = self._get_slides_info(tiles_list, self._load_tile(tiles_list[0]))
        img_mask = self._get_image_mask(img_height, img_width)
        self._find_tissue(tiles_list, img_mask)
        cores = self._filter_cores(self._get_cores(img_mask), img_height*img_width)
        grouped_cores = self._group_nearest_cores(cores, img_height)
        slide_json = self._build_slide_json(grouped_cores, zoom_level)
        with open(output_file, 'w') as ofile:
            ofile.write(json.dumps(slide_json))


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tiles-folder', type=str, required=True,
                        help='the folder containing all the tiles of a slide')
    parser.add_argument('--output-file', type=str, required=True, help='output JSON file')
    parser.add_argument('--log-level', type=str, default='INFO', help='log level (default=INFO)')
    parser.add_argument('--log-file', type=str, default=None, help='log file (default=stderr)')
    return parser


def main(argv):
    parser = get_parser()
    args = parser.parse_args(argv)
    cores_extractor = AutomaticCoresExtractor(args.log_level, args.log_file)
    cores_extractor.run(args.tiles_folder, args.output_file)


if __name__ == '__main__':
    main(sys.argv[1:])