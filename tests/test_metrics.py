# import pytest
#
# import numpy as np
# from reconai.math.metric import mse, ssim
#
#
# @pytest.mark.usefixtures("batcher")
# def test_ssim(batcher):
#     img_generator = batcher.items()
#     slideshow = next(img_generator)
#     image1 = slideshow[0, 0, :, :]
#
#     assert ssim(image1, image1) == 1
#
#
# @pytest.mark.usefixtures("batcher")
# def test_mse(batcher):
#     img_generator = batcher.items()
#     slideshow = next(img_generator)
#     image1 = slideshow[0, 0, :, :]
#
#     assert mse(image1, image1) == 0
#
#     assert np.isclose(mse(image1, image1 - 0.1), 0.01)
#
#
# @pytest.mark.usefixtures("batcher")
# def test_psnr(batcher):
#     pytest.skip('NYI')
